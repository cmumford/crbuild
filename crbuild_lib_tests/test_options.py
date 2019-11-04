#!/usr/bin/env python3

import os
import sys
import tempfile
import unittest

def GetAbsPathRelativeToThisFileDir(rel_path):
  return os.path.abspath(os.path.join(os.path.dirname(__file__),
                         rel_path))

sys.path.append(GetAbsPathRelativeToThisFileDir('..'))

from crbuild_lib import (adb, env, models, options)

class TestOptions(unittest.TestCase):

  mock_arm_device1_info = adb.DeviceInfo('emulator-5554', 28, 'arm64',
                                        ['com.android.webview'])
  mock_arm_device2_info = adb.DeviceInfo('emulator-5555', 29, 'arm64',
                                        ['com.android.webview'])
  mock_x86_device1_info = adb.DeviceInfo('emulator-5556', 27, 'x86',
                                        ['com.android.webview'])

  @staticmethod
  def _create_env(gclient_path=GetAbsPathRelativeToThisFileDir('gclient.txt')):
    environ = env.Env(os.getcwd(), gclient_path)
    environ.android_devices = {
        TestOptions.mock_arm_device1_info.serial: TestOptions.mock_arm_device1_info
    }
    return environ

  @staticmethod
  def _create_opts():
    return options.Options(TestOptions._create_env(), models.Configuration())

  def test_loading_no_error(self):
    self.assertEqual(options.Options.fixup_google_test_filter_args(None),
                     None)
    self.assertEqual(options.Options.fixup_google_test_filter_args(''),
                     None)
    self.assertEqual(options.Options.fixup_google_test_filter_args('foobar'),
                     ':foobar:')
    self.assertEqual(options.Options.fixup_google_test_filter_args(':foobar'),
                     ':foobar:')
    self.assertEqual(options.Options.fixup_google_test_filter_args(':foobar:'),
                     ':foobar:')

  @staticmethod
  def _create_android_opts():
    opts = TestOptions._create_opts()
    opts.buildopts.target_os = 'android'
    opts.buildopts.target_cpu = None
    opts.target_android_device_serial = None
    return opts

  def test_only_targets(self):
    opts = TestOptions._create_opts()
    opts.parse(['the_target'])
    self.assertListEqual(opts.active_targets, ['the_target'])
    self.assertEqual(None, opts.run_args)

  def test_os(self):
    opts = TestOptions._create_opts()
    opts.parse(['--os=android', '--cpu=arm64'])
    self.assertEqual('android', opts.buildopts.target_os)

  def test_default_target_os(self):
    opts = TestOptions._create_opts()
    opts.parse(['all'])
    # The default target OS is the first one in the gclient file.
    self.assertEqual('linux', opts.buildopts.target_os)

    tmp_file = tempfile.NamedTemporaryFile(mode='w')
    tmp_file.write('target_os = ["android", "chromeos", "linux"]')
    tmp_file.flush()
    opts = options.Options(TestOptions._create_env(tmp_file.name),
                           models.Configuration())
    opts.parse(['--cpu=arm64', 'all'])
    self.assertEqual('android', opts.buildopts.target_os)

  def test_set_android_defaults(self):
    # No devices at all defaults to the emulator.
    opts = TestOptions._create_android_opts()
    opts.buildopts.target_cpu = None
    opts.target_android_device_serial = None
    opts.env.android_devices = {}
    opts.set_android_defaults()
    self.assertEqual('android', opts.buildopts.target_os)
    self.assertEqual('x86', opts.buildopts.target_cpu)
    self.assertEqual(None, opts.target_android_device_serial)

    opts = TestOptions._create_android_opts()
    opts.set_android_defaults()
    self.assertEqual('android', opts.buildopts.target_os)
    self.assertEqual('arm64', opts.buildopts.target_cpu)
    # If there's only one device then no serial number is set
    # as adb will use the one attached device.
    self.assertEqual('emulator-5554', opts.target_android_device_serial)

    opts = TestOptions._create_android_opts()
    opts.buildopts.target_cpu = 'x86'
    opts.target_android_device_serial = '12345'
    opts.set_android_defaults()
    self.assertEqual('x86', opts.buildopts.target_cpu)
    self.assertEqual('12345', opts.target_android_device_serial)

    opts = TestOptions._create_android_opts()
    opts.buildopts.target_cpu = 'invalid'
    with self.assertRaises(Exception):
      opts.set_android_defaults()

    # If no cpu/device is given then we can only use them if
    # a device serial is provided.
    opts = TestOptions._create_android_opts()
    opts.env.android_devices = {
        TestOptions.mock_arm_device1_info.serial: TestOptions.mock_arm_device1_info,
        TestOptions.mock_arm_device2_info.serial: TestOptions.mock_arm_device2_info
    }
    with self.assertRaises(Exception):
      opts.set_android_defaults()

    # Multiple devices with only one matching the requested CPU.
    opts = TestOptions._create_android_opts()
    opts.env.android_devices = {
        TestOptions.mock_arm_device1_info.serial: TestOptions.mock_arm_device1_info,
        TestOptions.mock_x86_device1_info.serial: TestOptions.mock_x86_device1_info
    }
    opts.buildopts.target_cpu = 'x86'
    opts.set_android_defaults()
    self.assertEqual('x86', opts.buildopts.target_cpu)
    self.assertEqual('emulator-5556', opts.target_android_device_serial)

    # Multiple devices with zero matching the requested CPU.
    opts = TestOptions._create_android_opts()
    opts.env.android_devices = {
        TestOptions.mock_arm_device1_info.serial: TestOptions.mock_arm_device1_info,
        TestOptions.mock_x86_device1_info.serial: TestOptions.mock_x86_device1_info
    }
    opts.buildopts.target_cpu = 'x64'
    with self.assertRaises(Exception):
      opts.set_android_defaults()

  def test_invalid_os(self):
    opts = TestOptions._create_opts()
    with self.assertRaises(options.InvalidOption):
      opts.parse(['--os=unknownOS'])

  def test_invalid_cpu(self):
    opts = TestOptions._create_opts()
    with self.assertRaises(options.InvalidOption):
      opts.parse(['--cpu=unknownCPU'])

  def test_debug_and_release(self):
    opts = TestOptions._create_opts()
    with self.assertRaises(options.InvalidOption):
      opts.parse(['--debug', '--release'])

  def test_extra_args(self):
    opts = TestOptions._create_opts()
    opts.parse(['--os=linux', '-A', '-r', 'first', 'second', '--',
                'http://localhost:8000/index.html', 'last'])
    self.assertTrue(opts.buildopts.is_asan)
    self.assertFalse(opts.buildopts.is_debug)
    self.assertListEqual(opts.active_targets, ['first', 'second'])
    self.assertListEqual(opts.run_args, ['http://localhost:8000/index.html',
                                         'last'])

if __name__ == '__main__':
    unittest.main()
