#!/usr/bin/env python3

from .env import Env

class GClient(object):
  def __init__(self, gclient_path):
    self.contents = GClient.Read(gclient_path)
    if 'target_os' in self.contents:
      self.target_os = self.contents['target_os']
    else:
      self.target_os = [Env.get_build_platform()]
    self.default_target_os = self.target_os[0]

  @staticmethod
  def Read(gclient_path):
    result = {}
    with open(gclient_path, 'r') as f:
      try:
        exec(f.read(), {}, result)
      except SyntaxError as e:
        e.filename = gclient_path
        raise
    return result
