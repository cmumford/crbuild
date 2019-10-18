#!/usr/bin/env python3

import concurrent.futures
import copy
import json
import os
import subprocess
import sys
import tempfile
import time

from threading import Thread

class TestInfo(object):
  def __init__(self, wpt_dir, wpt_app, webdriver_binary, product, package_name,
               test):
    self.wpt_dir = wpt_dir
    self.wpt_app = wpt_app
    self.webdriver_binary = webdriver_binary
    self.product = product
    self.package_name = package_name
    self.test = test

class WptRunner(object):
  @staticmethod
  def _get_log_files(ua_name, devices):
    return [os.path.join(tempfile.gettempdir(), ua_name + '-' + d + '-log.json') \
            for d in devices]

  @staticmethod
  def _run_one(test_info):
    cmd = [
      test_info.wpt_app,
      'run',
      '--webdriver-binary=%s' % test_info.webdriver_binary,
      '--test-type=testharness',
      '--log-wptreport=%s' % test_info.logfile,
      '--log-tbpl=-',
      '--log-tbpl-level=info',
      '--this-chunk=%d' % test_info.chunk,
      '--total-chunks=%d' % test_info.total_chunks,
      '--chunk-type=hash',
      '--device-serial=%s' % test_info.device_serial,
    ]
    if test_info.package_name:
      cmd.append('--package-name=%s' % test_info.package_name)
    cmd.append(test_info.product)
    if test_info.test:
      cmd.append(test_info.test)
    subprocess.check_call(cmd)
    return 'WPT run chunk %d of %d completed without error' % \
        (test_info.chunk, test_info.total_chunks)

  @staticmethod
  def _generate_report(wpt_dir, ua_name, logfile):
    app = os.path.join(wpt_dir, 'tools', 'runner', 'report.py')
    report_file = os.path.join(wpt_dir, 'tools', 'runner', 'wpt_report.html')
    with open(report_file, 'w') as out_file:
      cmd = ['python', app, ua_name, logfile]
      subprocess.check_call(cmd, stdout=out_file)
    return report_file

  @staticmethod
  def _combine_logfiles(logfiles, combined):
    combined_data = {}
    for logfile in logfiles:
      with open(logfile) as f:
        data = json.load(f)
        if not combined_data:
          combined_data = data
        else:
          combined_data['results'].extend(data['results'])

    with open(combined, 'w') as f:
      json.dump(combined_data, f)

  @staticmethod
  def run(test_info, ua_name, devices):
    futures = []
    logfiles = WptRunner._get_log_files(ua_name, devices)
    with concurrent.futures.ThreadPoolExecutor() as executor:
      chunk = 1
      for (device, logfile) in zip(devices, logfiles):
        info = copy.copy(test_info)
        info.device_serial = device
        info.logfile = logfile
        info.chunk = chunk
        info.total_chunks = len(devices)
        futures.append(executor.submit(WptRunner._run_one, info))
        chunk += 1
    for future in futures:
      try:
        print(future.result())
      except subprocess.CalledProcessError as e:
        print('CalledProcessError:', e)
      except Exception as e:
        print('Exception:', e)
    combined_logfile = os.path.join(tempfile.gettempdir(),
                                    "wpt_log_%s.json" % ua_name)
    WptRunner._combine_logfiles(logfiles, combined_logfile)
    return WptRunner._generate_report(test_info.wpt_dir, ua_name,
                                      combined_logfile)

  @staticmethod
  def _run_adb(device, cmd):
    subprocess.check_call(['adb', '-s', device] + cmd)

  @staticmethod
  def disable_animations(device):
    WptRunner._run_adb(device, ['shell', 'settings', 'put', 'global',
                                'window_animation_scale', '0'])
    WptRunner._run_adb(device, ['shell', 'settings', 'put', 'global',
                                'transition_animation_scale', '0'])
    WptRunner._run_adb(device, ['shell', 'settings', 'put', 'global',
                                'animator_duration_scale', '0'])

  @staticmethod
  def setup_device_command_line(device):
    shell_cmd = "echo '_ --host-resolver-rules=\"MAP nonexistent.*.test " \
                "~NOTFOUND, MAP *.test 127.0.0.1\"' > " \
                "/data/local/tmp/webview-command-line"
    WptRunner._run_adb(device, ['shell', shell_cmd])

