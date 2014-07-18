# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sublime, sublime_plugin
import os, sys, subprocess, codecs, re, webbrowser
from threading import Timer

try:
  import commands
except ImportError:
  pass

PLUGIN_FOLDER = os.path.dirname(os.path.realpath(__file__))
RC_FILE = ".jshintrc"
SETTINGS_FILE = "JSHint.sublime-settings"
KEYMAP_FILE = "Default ($PLATFORM).sublime-keymap"
OUTPUT_VALID = b"*** JSHint output ***"

class JshintCommand(sublime_plugin.TextCommand):
  def run(self, edit, show_regions=True, show_panel=True):
    JshintEventListeners.reset()

    # Make sure we're only linting javascript files.
    if self.file_unsupported():
      return

    # Get the current text in the buffer.
    bufferText = self.view.substr(sublime.Region(0, self.view.size()))
    # ...and save it in a temporary file. This allows for scratch buffers
    # and dirty files to be linted as well.
    namedTempFile = ".__temp__"
    tempPath = PLUGIN_FOLDER + "/" + namedTempFile
    print("Saving buffer to: " + tempPath)
    f = codecs.open(tempPath, mode='w', encoding='utf-8')
    f.write(bufferText)
    f.close()

    node = PluginUtils.get_node_path()
    output = ""
    try:
      filePath = self.view.file_name()
      scriptPath = PLUGIN_FOLDER + "/scripts/run.js"
      output = PluginUtils.get_output([node, scriptPath, tempPath, filePath or "?"])

      # Make sure the correct/expected output is retrieved.
      if output.find(OUTPUT_VALID) == -1:
        print(output)
        cmd = node + " " + scriptPath + " " + tempPath + " " + filePath
        msg = "Command " + cmd + " created invalid output"
        raise Exception(msg)

    except:
      # Something bad happened.
      print("Unexpected error({0}): {1}".format(sys.exc_info()[0], sys.exc_info()[1]))

      # Usually, it's just node.js not being found. Try to alleviate the issue.
      msg = "Node.js was not found in the default path. Please specify the location."
      if sublime.ok_cancel_dialog(msg):
        PluginUtils.open_sublime_settings(self.view.window())
      else:
        msg = "You won't be able to use this plugin without specifying the path to Node.js."
        sublime.error_message(msg)
      return

    # Dump any diagnostics from run.js
    diagEndIndex = output.find(OUTPUT_VALID)
    diagMessage = output[:diagEndIndex]
    print(diagMessage.decode())

    # Remove the output identification marker (first line).
    output = output[diagEndIndex + len(OUTPUT_VALID) + 1:]

    # We're done with linting, rebuild the regions shown in the current view.
    self.view.erase_regions("jshint_errors")
    os.remove(tempPath)

    if len(output) > 0:
      regions = []
      menuitems = []

      # For each line of jshint output (errors, warnings etc.) add a region
      # in the view and a menuitem in a quick panel.
      for line in output.decode().splitlines():
        try:
          lineNo, columnNo, description = line.split(" :: ")
        except:
          continue

        symbolName = re.match("('[^']+')", description)
        hintPoint = self.view.text_point(int(lineNo) - 1, int(columnNo) - 1)
        if symbolName:
          hintRegion = self.view.word(hintPoint)
        else:
          hintRegion = self.view.line(hintPoint)

        menuitems.append(lineNo + ":" + columnNo + " " + description)
        regions.append(hintRegion)
        JshintEventListeners.errors.append((hintRegion, description))

      if show_regions:
        self.add_regions(regions)
      if show_panel:
        self.view.window().show_quick_panel(menuitems, self.on_chosen)

  def file_unsupported(self):
    file_path = self.view.file_name()
    view_settings = self.view.settings()
    has_js_extension = file_path != None and bool(re.search(r'\.jsm?$', file_path))
    has_js_syntax = bool(re.search("JavaScript", view_settings.get("syntax"), re.I))
    has_json_syntax = bool(re.search("JSON", view_settings.get("syntax"), re.I))
    return has_json_syntax or (not has_js_extension and not has_js_syntax)

  def add_regions(self, regions):
    packageName = (PLUGIN_FOLDER.split(os.path.sep))[-1]

    if int(sublime.version()) >= 3000:
      icon = "Packages/" + packageName + "/warning.png"
      self.view.add_regions("jshint_errors", regions, "keyword", icon,
        sublime.DRAW_EMPTY |
        sublime.DRAW_NO_FILL |
        sublime.DRAW_NO_OUTLINE |
        sublime.DRAW_SQUIGGLY_UNDERLINE)
    else:
      icon = ".." + os.path.sep + packageName + os.path.sep + "warning"
      self.view.add_regions("jshint_errors", regions, "keyword", icon,
        sublime.DRAW_EMPTY |
        sublime.DRAW_OUTLINED)

  def on_chosen(self, index):
    if index == -1:
      return

    # Focus the user requested region from the quick panel.
    region = JshintEventListeners.errors[index][0]
    region_cursor = sublime.Region(region.begin(), region.begin())
    selection = self.view.sel()
    selection.clear()
    selection.add(region_cursor)
    self.view.show(region_cursor)

    if not PluginUtils.get_pref("highlight_selected_regions"):
      return

    self.view.erase_regions("jshint_selected")
    self.view.add_regions("jshint_selected", [region], "meta")

class JshintEventListeners(sublime_plugin.EventListener):
  timer = None
  errors = []

  @staticmethod
  def reset():
    self = JshintEventListeners

    # Invalidate any previously set timer.
    if self.timer != None:
      self.timer.cancel()

    self.timer = None
    self.errors = []

  @staticmethod
  def on_modified(view):
    self = JshintEventListeners
    # Continue only if the plugin settings allow this to happen.
    # This is only available in Sublime 3.
    if int(sublime.version()) < 3000:
      return
    if not PluginUtils.get_pref("lint_on_edit"):
      return

    # Re-run the jshint command after a second of inactivity after the view
    # has been modified, to avoid regions getting out of sync with the actual
    # previously linted source code.
    if self.timer != None:
      self.timer.cancel()

    timeout = PluginUtils.get_pref("lint_on_edit_timeout")
    self.timer = Timer(timeout, lambda: view.window().run_command("jshint", { "show_panel": False }))
    self.timer.start()

  @staticmethod
  def on_post_save(view):
    # Continue only if the current plugin settings allow this to happen.
    if PluginUtils.get_pref("lint_on_save"):
      view.window().run_command("jshint", { "show_panel": False })

  @staticmethod
  def on_load(view):
    # Continue only if the current plugin settings allow this to happen.
    if PluginUtils.get_pref("lint_on_load"):
      v = view.window() if int(sublime.version()) < 3000 else view
      v.run_command("jshint", { "show_panel": False })

  @staticmethod
  def on_selection_modified(view):
    caret_region = view.sel()[0]

    for message_region, message_text in JshintEventListeners.errors:
      if message_region.intersects(caret_region):
        sublime.status_message(message_text)
        return
    else:
      sublime.status_message("")

class JshintSetLintingPrefsCommand(sublime_plugin.TextCommand):
  def run(self, edit):
    PluginUtils.open_config_rc(self.view.window())

class JshintSetPluginOptionsCommand(sublime_plugin.TextCommand):
  def run(self, edit):
    PluginUtils.open_sublime_settings(self.view.window())

class JshintSetKeyboardShortcutsCommand(sublime_plugin.TextCommand):
  def run(self, edit):
    PluginUtils.open_sublime_keymap(self.view.window(), {
      "windows": "Windows",
      "linux": "Linux",
      "osx": "OSX"
    }.get(sublime.platform()))

class JshintSetNodePathCommand(sublime_plugin.TextCommand):
  def run(self, edit):
    PluginUtils.open_sublime_settings(self.view.window())

class JshintClearAnnotationsCommand(sublime_plugin.TextCommand):
  def run(self, edit):
    JshintEventListeners.reset()
    self.view.erase_regions("jshint_errors")
    self.view.erase_regions("jshint_selected")

class PluginUtils:
  @staticmethod
  def get_pref(key):
    return sublime.load_settings(SETTINGS_FILE).get(key)

  @staticmethod
  def open_config_rc(window):
    window.open_file(PLUGIN_FOLDER + "/" + RC_FILE)

  @staticmethod
  def open_sublime_settings(window):
    window.open_file(PLUGIN_FOLDER + "/" + SETTINGS_FILE)

  @staticmethod
  def open_sublime_keymap(window, platform):
    window.open_file(PLUGIN_FOLDER + "/" + KEYMAP_FILE.replace("$PLATFORM", platform))

  @staticmethod
  def exists_in_path(cmd):
    # Can't search the path if a directory is specified.
    assert not os.path.dirname(cmd)
    path = os.environ.get("PATH", "").split(os.pathsep)
    extensions = os.environ.get("PATHEXT", "").split(os.pathsep)

    # For each directory in PATH, check if it contains the specified binary.
    for directory in path:
      base = os.path.join(directory, cmd)
      options = [base] + [(base + ext) for ext in extensions]
      for filename in options:
        if os.path.exists(filename):
          return True

    return False

  @staticmethod
  def get_node_path():
    # Simply using `node` without specifying a path sometimes doesn't work :(
    if PluginUtils.exists_in_path("nodejs"):
      return "nodejs"
    elif PluginUtils.exists_in_path("node"):
      return "node"
    else:
      platform = sublime.platform();
      node = PluginUtils.get_pref("node_path").get(platform)
      print("Using node.js path on '" + platform + "': " + node)
      return node

  @staticmethod
  def get_output(cmd):
    if int(sublime.version()) < 3000:
      if sublime.platform() != "windows":
        # Handle Linux and OS X in Python 2.
        run = '"' + '" "'.join(cmd) + '"'
        return commands.getoutput(run)
      else:
        # Handle Windows in Python 2.
        # Prevent console window from showing.
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, startupinfo=startupinfo).communicate()[0]
    else:
      # Handle all OS in Python 3.
      run = '"' + '" "'.join(cmd) + '"'
      return subprocess.check_output(run, stderr=subprocess.STDOUT, shell=True)
