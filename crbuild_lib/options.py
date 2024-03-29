#!/usr/bin/env python3

import argparse
import multiprocessing
import os
import platform
import subprocess
import sys

from .build_settings import BuildSettings
from .gclient import GClient
from . import git

class InvalidOption(Exception):
  pass

class Options(object):

  valid_arm_cpus = ('arm', 'arm64', 'armeabi', 'armeabi-v7a', 'armv8-a',
                    'arm64-v8a')
  valid_x86_cpus = ('x86', 'x64')
  valid_mips_cpus = ('mipsel', 'mips64el')
  valid_cpus = valid_arm_cpus + valid_x86_cpus + valid_mips_cpus

  def __init__(self, env, config):
    self.gclient = GClient(env.gclient_path)
    self._config = config
    self.env = env
    self.buildopts = BuildSettings(git.CurrentBranch(),
                                   self.gclient.default_target_os)
    self.keep_going = True
    self.sudo_pwd = None
    self.verbosity = 0
    self.print_cmds = True
    self.noop = False
    self.regyp = False
    self.buildopts.goma_dir = Options._get_goma_dir()
    if self.buildopts.use_goma:
      self.buildopts.use_goma = Options._is_goma_running()
    self.llvm_path = os.path.join(env.src_root_dir, 'third_party', 'llvm-build',
                                  'Release+Asserts', 'bin')
    if not os.path.exists(self.llvm_path):
      self.buildopts.use_clang = False
    self.clobber = False
    self.active_targets = []
    self.run_debugger = False
    self.out_dir = 'out'
    self.use_rr = False
    self.run_args = None
    self.layout_dir = os.path.join(env.src_root_dir, 'third_party', 'WebKit',
                                   'LayoutTests')
    self.jobs = int(multiprocessing.cpu_count() * 120 / 100)
    self.test_jobs = self.jobs
    self.debugger = 'gdb'
    self.profile = False
    # https://chromium.googlesource.com/chromium/src/+/master/docs/profiling.md
    self.heap_profiling = False
    self.profile_file = '/tmp/cpuprofile'
    self.run_targets = True
    self.gtest = None
    self.target_android_device_serial = None

  @staticmethod
  def _goma_ctl():
    if os.name == 'nt':
      return 'goma_ctl.bat'
    else:
      return 'goma_ctl'

  @staticmethod
  def _get_goma_dir():
    # First line of stdout is the directory.
    cmd = [Options._goma_ctl(), 'goma_dir']
    for line in subprocess.check_output(cmd, stderr=subprocess.DEVNULL).splitlines():
      return line.decode('utf-8').strip()
    return None

  # crbuild -d [<target1>..<targetn>] -- <run_arg1>, <run_argn>
  # argparse can't deal with multiple positional arguments. So before we parse
  # args we strip off the "bare double dash" args which we pass to an executable
  # *if* we wind up running one.
  def _strip_run_positional_args(self, args):
    if '--' in args:
      positional_start_idx = args.index('--')
      self.run_args = args[positional_start_idx+1:]
      return args[:positional_start_idx]
    return args

  @staticmethod
  def str2bool(v):
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
      return True
    if v.lower() in ('no', 'false', 'f', 'n', '0'):
      return False
    raise argparse.ArgumentTypeError('Boolean value expected.')

  @staticmethod
  def fixup_google_test_filter_args(val):
    """Parse the --gtest options for --gtest_filter."""
    # prefix/suffixing tests with ':' shouldn't be necessary according to
    # https://github.com/google/googletest/blob/master/googletest/docs/V1_7_AdvancedGuide.md#running-a-subset-of-the-tests
    # but experimentation indicates otherwise.
    if val is None:
      return None
    if val.strip() == '':
      return None
    ret = val
    if not ret.startswith(':'):
      ret = ':' + ret
    if not ret.endswith(':'):
      ret = ret + ':'
    return ret

  def _get_target_help_epilog(self):
    target_info = []
    for _, target in self._config.targets.items():
      target_info.append((target.name, target.title))
    epilog = ''
    for info in sorted(target_info, key=lambda info: info[0]):
      if info[1]:
        epilog += '\n%s: %s' % (info[0], info[1])
      else:
        epilog += '\n%s' % info[0]
    return epilog

  def create_parser(self):
    desc = 'A script to make building and running Chromium targets easier.'
    parser = argparse.ArgumentParser(description=desc,
                                     formatter_class=argparse.RawTextHelpFormatter,
                                     epilog=self._get_target_help_epilog())
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Do a debug build (default: debug)')
    parser.add_argument('-r', '--release', action='store_true',
                        help='Do a release build (default: debug)')
    parser.add_argument('-g', '--gyp', action='store_true',
                        help='Re-gyp before building')
    parser.add_argument('-v', '--verbose', action='count',
                        help='Be verbose, can be used multiple times')
    parser.add_argument('-c', '--clobber', action='store_true',
                        help='Delete out dir before building')
    parser.add_argument('-n', '--noop', action='store_true',
                        help="Don't do anything, print what would be done")
    parser.add_argument('-R', '--no-run', action='store_true',
                        help='Do not run targets after building.')
    parser.add_argument('--cfi',
                        type=Options.str2bool, nargs='?',
                        const=True, default=self.buildopts.is_cfi,
                        help='Do a CFI build (release only) (default: %s).' % \
                        self.buildopts.is_cfi)
    parser.add_argument('-A', '--asan', action='store_true',
                        help="Do a SyzyASan build")
    parser.add_argument('-t', '--tsan', action='store_true',
                        help="Do a TSan build")
    parser.add_argument('-l', '--lsan', action='store_true',
                        help="Do a LSan build")
    parser.add_argument('-m', '--msan', action='store_true',
                        help="Do a MSan build")
    parser.add_argument('-C', '--component',
                        type=Options.str2bool, nargs='?',
                        const=True, default=self.buildopts.is_component_build,
                        help="Do a component build (default: %s)." % \
                        self.buildopts.is_component_build)
    parser.add_argument('--dcheck',
                        type=Options.str2bool, nargs='?',
                        const=True, default=self.buildopts.dcheck_always_on,
                        help="Always enable DCHECK (default: %s)." % \
                        self.buildopts.dcheck_always_on)
    parser.add_argument('--official',
                        type=Options.str2bool, nargs='?',
                        const=True, default=self.buildopts.is_official_build,
                        help="Do an official (default: %s)." % \
                        self.buildopts.is_official_build)
    parser.add_argument('--branded',
                        type=Options.str2bool, nargs='?',
                        const=True, default=self.buildopts.is_chrome_branded,
                        help="Do a Chrome branded build (default: %s)." % \
                        self.buildopts.is_chrome_branded)
    parser.add_argument('--goma',
                        type=Options.str2bool, nargs='?',
                        const=True, default=self.buildopts.use_goma,
                        help="Use goma for building (default: %s)." % \
                        self.buildopts.use_goma)
    parser.add_argument('--os', type=str, nargs=1, help='The target OS')
    parser.add_argument('--cpu', type=str, nargs=1, help='The target CPU '
                                                         'architecture')
    parser.add_argument('--device', type=str, nargs=1, help='The target Android'
                                                            ' device.')
    parser.add_argument('-p', '--profile', action='store_true',
                        help="Profile the executable")
    parser.add_argument('-j', '--jobs',
                        help="Num jobs when both building & running")
    parser.add_argument('--rr', action='store_true',
                        help="Record app using rr (https://rr-project.org/)")
    parser.add_argument('--fuzzer', action='store_true',
                        help="Do a fuzzer build (implies asan).")
    parser.add_argument('-V', '--valgrind', action='store_true',
                        help="Build for Valgrind (memcheck) (default: %s)" % self.buildopts.valgrind)
    parser.add_argument('-D', '--debugger', action='store_true',
                        help="Run the debug executable profile (default: %s)" % self.run_debugger)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--use-clang', action='store_true',
                        help="Use the clang compiler (default %s)" % self.buildopts.use_clang)
    group.add_argument('--no-use-clang', action='store_true',
                        help="Use the clang compiler (default %s)" % (not self.buildopts.use_clang))
    parser.add_argument('--gtest', type=str,
                        help="The string to pass to the --gtest_filter parameter.")
    targets_help = \
"""Target(s) to build/run. The target name can be one
of the predefined items defined in config.yml. If
not then it is assumed to be a target defined in the
GN files."""
    parser.add_argument('target', nargs='*',
                        help=targets_help)
    return parser

  def parse(self, args):
    parser = self.create_parser()
    namespace = parser.parse_args(self._strip_run_positional_args(args))

    if namespace.debug and namespace.release:
      raise InvalidOption('Can only do debug OR release, not both.')
    if namespace.debug:
      self.buildopts.is_debug = True
    elif namespace.release:
      self.buildopts.is_debug = False
    self.regyp = namespace.gyp
    self.clobber = namespace.clobber
    if self.clobber:
      self.regyp = True
    if namespace.verbose:
      self.verbosity = namespace.verbose
    self.buildopts.dcheck_always_on = namespace.dcheck
    self.buildopts.is_chrome_branded = namespace.branded
    self.buildopts.is_component_build = namespace.component
    self.buildopts.is_official_build = namespace.official
    self.buildopts.use_goma = namespace.goma
    if self.buildopts.is_official_build and self.buildopts.is_component_build:
      raise InvalidOption('Official builds cannot be component builds.')
    if namespace.noop:
      self.noop = True
    if namespace.no_run:
      self.run_targets = False
    if namespace.use_clang:
      self.buildopts.use_clang = True
    elif namespace.no_use_clang:
      self.buildopts.use_clang = False
    if self.buildopts.use_clang and not os.path.exists(self.llvm_path):
      print("Can't use clang (llvm path !exists)", file=sys.stderr)
      self.buildopts.use_clang = False
    if namespace.valgrind:
      self.buildopts.valgrind = True
    if namespace.debugger:
      self.run_debugger = True
    if namespace.jobs:
      self.jobs = namespace.jobs
    if namespace.fuzzer:
      self.buildopts.use_libfuzzer = True
      self.buildopts.is_asan = True
    if namespace.lsan or namespace.asan:
      self.buildopts.is_lsan = True
      self.buildopts.is_asan = True
    if namespace.msan:
      self.buildopts.is_msan = True
    if namespace.rr:
      self.use_rr = True
    self.buildopts.is_cfi = namespace.cfi
    if self.buildopts.is_cfi:
      if self.buildopts.is_debug:
        raise InvalidOption('CFI build is release build only.')
      if self.buildopts.is_component_build:
        raise InvalidOption('CFI build is static build only.')
    if namespace.os:
      target_os = namespace.os[0]
      if target_os not in self.gclient.target_os:
        raise InvalidOption(str.format('{0} must be one of {1}',
                                        target_os, self.gclient.target_os))
      self.buildopts.target_os = target_os
    if self.buildopts.target_os == 'android':
      # hard-code Android to false until crbug.com/996285 is fixed.
      self.buildopts.is_component_build = False
    if namespace.device:
      self.target_android_device_serial = namespace.device[0]
    if namespace.cpu:
      self.buildopts.target_cpu = namespace.cpu[0]
      if not self.buildopts.target_cpu in Options.valid_cpus:
        raise InvalidOption(
            str.format('"{0}" is not a valid CPU. Must be one of {1}',
                       self.buildopts.target_cpu, Options.valid_cpus))
    if self.buildopts.target_os == 'linux':
      self.buildopts.gyp_defines.add('linux_use_debug_fission=0')
    if ((self.buildopts.target_os == 'win' or
         self.buildopts.target_os == 'linux') and
        self.buildopts.is_component_build):
      # Should read in chromium.gyp_env and append to those values
      self.buildopts.gyp_defines.add('component=shared_library')
    if namespace.tsan:
      self.buildopts.is_tsan = True
      self.buildopts.is_component_build = False
    if self.buildopts.is_asan:
      self.buildopts.is_component_build = False
      if self.buildopts.target_os == 'linux':
        if namespace.no_use_clang:
          print("ASan *is* clang to don't tell me not to use it.",
                file=sys.stderr)
        self.buildopts.gyp_defines.add('asan=1')
        self.buildopts.gyp_defines.add('lsan=1')
        self.buildopts.gyp_defines.add('clang=1')
        self.buildopts.gyp_defines.add('use_allocator=none')
        self.buildopts.gyp_defines.add('enable_ipc_fuzzer=1')
        self.buildopts.gyp_defines.add('release_extra_cflags="-g -O1 '
                                       '-fno-inline-functions -fno-inline"')
        self.buildopts.gyp_generator_flags.add("output_dir=%s" % self.out_dir)
      elif self.buildopts.target_os == 'win':
        self.buildopts.gyp_defines.add('syzyasan=1')
        self.buildopts.gyp_defines.add('win_z7=1')
        self.buildopts.gyp_defines.add('chromium_win_pch=0')
        self.buildopts.gyp_defines.add('chrome_multiple_dll=0')
        self.buildopts.gyp_generators = 'ninja'
        # According to docs SyzyASan not yet compatible shared library.
        if 'component=shared_library' in self.buildopts.gyp_defines:
          self.buildopts.gyp_defines.remove('component=shared_library')
        self.buildopts.gyp_defines.add('component=static_library')
        if 'disable_nacl=1' in self.buildopts.gyp_defines:
          self.buildopts.gyp_defines.remove('disable_nacl=1')
      elif self.buildopts.target_os == 'android':
        self.buildopts.gyp_defines.add('asan=1')
        if self.buildopts.is_component_build:
          self.buildopts.gyp_defines.add('component=shared_library')
      elif platform.system() == 'mac':
        self.buildopts.gyp_defines.add('asan=1')
        self.buildopts.gyp_defines.add('target_arch=x64')
        self.buildopts.gyp_defines.add('host_arch=x64')
    self.buildopts.gyp_defines.add('OS=%s' % self.buildopts.target_os)
    if self.heap_profiling:
      if not self.buildopts.is_debug:
        raise InvalidOption('Heap profiling requires a debug build.')
      self.buildopts.enable_profiling = True
      self.buildopts.enable_callgrind = True
    if namespace.profile:
      self.profile = True
      self.buildopts.gyp_defines.add('profiling=1')
    if self.buildopts.is_asan and self.buildopts.is_debug:
      raise InvalidOption('ASan only works on a release build.')
    if self.buildopts.is_msan and self.buildopts.is_debug:
      raise InvalidOption('MSan only works on a release build.')
    if self.buildopts.is_tsan and self.buildopts.is_debug:
      raise InvalidOption('TSan only works on a release build.')
    if self.buildopts.is_tsan and self.buildopts.is_asan:
      raise InvalidOption("Can't do both TSan and ASan builds.")
    self.gtest = Options.fixup_google_test_filter_args(namespace.gtest)
    self.active_targets = namespace.target
    if self.buildopts.target_os == 'android':
      self.set_android_defaults()
      if self.target_android_device_serial:
        # system_webview_package_name only works on N+.
        # Also, this may change args.gn every build, but that's OK.
        self.buildopts.system_webview_package_name = \
            self._get_system_webview_package_name(self.target_android_device_serial)

  @staticmethod
  def _build_cpu_matches_device(build_cpu, device_cpu):
    # https://chromium.googlesource.com/chromium/src/+/HEAD/docs/android_build_instructions.md#figuring-out-target_cpu
    assert build_cpu
    if build_cpu == device_cpu:
      return True
    if build_cpu == 'arm':
      return device_cpu in ('armeabi', 'armeabi-v7a')
    if build_cpu == 'arm64':
      return device_cpu in ('arm64-v8a')
    return False

  def set_android_defaults(self):
    """Determine the android device's cpu/serial values.

    Generally the rule is:
      1. If both are specified then validate and use.
      2. If none are specified then:
        a. If only one device then use it.
        b. else error.
    """
    assert self.buildopts.target_os == 'android'
    if self.buildopts.target_cpu and \
        self.buildopts.target_cpu not in Options.valid_cpus:
      raise Exception(str.format(
          "target CPU (\"{0}\") doesn't match default device (\"{1}\")",
          self.buildopts.target_cpu, device_cpu))

    # User supplied args always override.
    if self.target_android_device_serial and self.buildopts.target_cpu:
      return

    # If neither specified.
    if not self.target_android_device_serial and not self.buildopts.target_cpu:
      num_devices = len(self.env.android_devices)
      if num_devices == 0:
        self.buildopts.target_cpu = 'x86'
        return
      if num_devices == 1:
        only_device_serial = next(iter(self.env.android_devices))
        device_info = self.env.android_devices[only_device_serial]
        self.buildopts.target_cpu = device_info.cpu_abi
        self.target_android_device_serial = device_info.serial
        return
      raise Exception('There are ' + str(num_devices) + ' devices. Specify one with '
                      '--cpu or --device options.')

    if self.buildopts.target_cpu:
      # Find the first device whose CPU type matches the target CPU. If there
      # is more than one then error because this is ambiguous.
      matching_device = None
      cpus = []
      for _, device_info in self.env.android_devices.items():
        cpus.append(device_info.cpu_abi)
        if Options._build_cpu_matches_device(self.buildopts.target_cpu,
                                             device_info.cpu_abi):
          if matching_device:
            raise Exception(str.format('There are multiple devices with "%s"'
                                       ' CPU. Specify with --device option.',
                                       self.buildopts.target_cpu))
          matching_device = device_info
      if not matching_device:
        raise Exception('No device with CPU matching "' + \
                        self.buildopts.target_cpu + '"' + str(cpus))
      self.target_android_device_serial = matching_device.serial

  def _get_default_device(self):
    device_info = self.env.android_devices
    if len(device_info) == 1:
      return list(device_info.keys())[0]
    for device_name, _ in device_info.items():
      if self.buildopts.target_cpu in Options.valid_arm_cpus \
          and not device_name.startswith('emulator-'):
        return device_name
      elif self.buildopts.target_cpu in Options.valid_x86_cpus \
          and device_name.startswith('emulator-'):
        return device_name
    return None

  def _get_allowed_android_packages(self, device):
    # https://chromium.googlesource.com/chromium/src/+/HEAD/android_webview/docs/build-instructions.md#changing-package-name
    device_info = self.env.android_devices[device]
    code_letter = device_info.release_letter()
    has_gms = device_info.has_gms()
    if code_letter == 'K':
      # Not sure this is correct.
      return ['com.android.webview']
    elif code_letter >= 'L' and code_letter <= 'M':
      if has_gms:
        return ['com.google.android.webview']
      else:
        return ['com.android.webview']
    elif code_letter >= 'N' and code_letter <= 'P':
      if has_gms:
        # Should also test for TV/car devices.
        return ['com.android.chrome',
                'com.chrome.beta',
                'com.chrome.dev',
                'com.chrome.canary',
                'com.google.android.apps.chrome',
                'com.google.android.webview']
      else:
        return ['com.android.webview']
    elif code_letter >= 'Q':
      # Not sure this is correct.
      return ['com.android.webview']
    raise Exception('Unsupported platform: %s' % code_letter)

  def _get_system_webview_package_name(self, device):
    # See https://chromium.googlesource.com/chromium/src/+/HEAD/android_webview/docs/quick-start.md#my-package-isn_t-in-the-list
    # See https://chromium.googlesource.com/chromium/src/+/HEAD/android_webview/docs/quick-start.md#setting-up-the-build
    assert self.buildopts.target_os == 'android'

    # Not used here, but at present handy to keep around.
    target_default_packages_names = {
      'monochrome_apk': 'com.google.android.apps.chrome',
      'monochrome_public_apk': 'org.chromium.chrome',
      'system_webview_apk': 'com.android.webview',
      'system_webview_google_apk': 'com.google.android.webview',
      'system_webview_shell_apk': 'org.chromium.webview_shell',
      'system_webview_shell_layout_test_apk': 'org.chromium.webview_shell.test',
      'system_webview_uninstall': 'com.android.webview',
      'webview_instrumentation_apk': 'org.chromium.android_webview.shell',
      'webview_instrumentation_test_apk': 'org.chromium.android_webview.test',
    }

    desired_package_name = 'com.chrome.canary'
    allowed_package_names = self._get_allowed_android_packages(device)
    if desired_package_name in allowed_package_names:
      return desired_package_name
    return allowed_package_names[int(len(allowed_package_names) / 2)]

  @staticmethod
  def _is_goma_running():
    cmd = [Options._goma_ctl(), 'status']
    for line in subprocess.check_output(cmd, stderr=subprocess.DEVNULL).splitlines():
      line = line.decode('utf-8')
      if line.endswith('status: http://127.0.0.1:8088 ok'):
        return True
    return False
