#!/usr/bin/env python3

import platform
import sys

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'

class Cmd(object):
  '''Simple wrapper for executing and printing commands.'''


  @staticmethod
  def _item_to_string(item, add_quotes, quote_flags):
    assert(isinstance(item, str))
    equals_idx = item.find('=')
    if equals_idx != -1:
      lhs = item[:equals_idx]
      rhs = item[equals_idx+1:]
      return '%s=%s' % (Cmd._item_to_string(lhs, add_quotes, False),
                        Cmd._item_to_string(rhs, add_quotes, True))

    if not add_quotes:
      return item
    if ' ' in item or '*' in item or (quote_flags and '--' in item):
      return '"%s"' % item
    return item

  @staticmethod
  def list_to_string(cmd, add_quotes):
    assert(isinstance(cmd, list))
    return ' '.join([Cmd._item_to_string(i, add_quotes=add_quotes,
                                          quote_flags=False) for i in cmd])

  @staticmethod
  def _print(cmd, env_vars, color, add_quotes):
    '''Print the command to stdout in the specified color (if able to).

    May supply a string of list of strings.'''
    if (isinstance(cmd, list)):
      str_cmd = Cmd.list_to_string(cmd, add_quotes)
    else:
      assert isinstance(cmd, str) or isinstance(cmd, unicode)
      str_cmd = cmd
    if env_vars:
      str_cmd = env_vars + ' ' + str_cmd
    if Cmd._can_output_color():
      print("%s%s%s" % (color, str_cmd, bcolors.ENDC))
    else:
      print(str_cmd)

  @staticmethod
  def print_ok(cmd, env_vars, add_quotes):
    '''Print the OK command to stdout.

    May supply a string of list of strings.'''
    Cmd._print(cmd, env_vars, bcolors.OKBLUE, add_quotes)

  @staticmethod
  def print_error(cmd, env_vars, add_quotes):
    '''Print the error command to stdout.

    May supply a string of list of strings.
    |env_vars| is a printable string that would appear on the command-line
    such as 'FOO="bar" BAZ="45"'.
    '''
    if isinstance(cmd, list):
      cmd = ['Failed: '] + cmd
    else:
      cmd = 'Failed: ' + cmd
    Cmd._print(cmd, env_vars, bcolors.FAIL, add_quotes)

  @staticmethod
  def _can_output_color():
    if platform.system() == 'Windows':
      return False
    else:
      return sys.stdout.isatty()
