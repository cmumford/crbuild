#!/usr/bin/env python

from __future__ import print_function

import os
import sys
import yaml

SRC_DIR='/usr/local/google/home/cmumford/work/ssd/chrome/src'
sys.path.append(os.path.join(SRC_DIR, 'third_party', 'catapult', 'devil'))
from devil.android import device_utils

def get_config_file_path():
  """Return the path to this application's configuration file."""
  return os.path.join(os.path.dirname(__file__), 'wpt.yml')

if __name__ == '__main__':
  config = None
  with open(get_config_file_path(), 'r') as stream:
    config = yaml.safe_load(stream)
  print(config)

  devices = device_utils.DeviceUtils.HealthyDevices()
  for d in devices:
    print(d)
