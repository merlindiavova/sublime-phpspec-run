import re
import os
import shutil

from sublime import active_window
from sublime import cache_path
from sublime import ENCODED_POSITION
from sublime import load_resource
from sublime import message_dialog
from sublime import platform
from sublime import status_message
import sublime_plugin


_DEBUG = bool(os.getenv('SUBLIME_PHPSPEC_DEBUG'))

if _DEBUG:
    def debug_message(msg, *args):
        if args:
            msg = msg % args
        print('PHPSpec Run: ' + msg)
else:  # pragma: no cover
    def debug_message(msg, *args):
        pass


def is_debug(view=None):
    if view:
        phpspec_debug = view.settings().get('phpspec-run.debug')
        return phpspec_debug or (
            phpspec_debug is not False and view.settings().get('debug')
        )
    else:
        return _DEBUG


def get_window_setting(key, default=None, window=None):
    if not window:
        window = active_window()

    if window.settings().has(key):
        return window.settings().get(key)

    view = window.active_view()

    if view and view.settings().has(key):
        return view.settings().get(key)

    return default


def set_window_setting(key, value, window):
    window.settings().set(key, value)


def find_phpspec_configuration_file(file_name, folders):
    """
    Find the first PHPSpec configuration file.

    Finds either phpspec.yml or phpspec.yml.dist, in {file_name} directory or
    the nearest common ancestor directory in {folders}.
    """
    debug_message('find configuration for \'%s\'', file_name)
    debug_message('found %d folders %s', len(folders) if folders else 0, folders)

    if file_name is None:
        return None

    if not isinstance(file_name, str):
        return None

    if not len(file_name) > 0:
        return None

    if folders is None:
        return None

    if not isinstance(folders, list):
        return None

    if not len(folders) > 0:
        return None

    ancestor_folders = []
    common_prefix = os.path.commonprefix(folders)
    parent = os.path.dirname(file_name)
    while parent not in ancestor_folders and parent.startswith(common_prefix):
        ancestor_folders.append(parent)
        parent = os.path.dirname(parent)

    ancestor_folders.sort(reverse=True)

    debug_message('found %d common ancestors %s', len(ancestor_folders), ancestor_folders)

    candidate_configuration_file_names = ['phpspec.yml', 'phpspec.yml.dist']
    debug_message('candidate configuration files %s', candidate_configuration_file_names)
    for folder in ancestor_folders:
        debug_message('looking at \'%s\'', folder)
        for file_name in candidate_configuration_file_names:
            phpspec_configuration_file = os.path.join(folder, file_name)
            if os.path.isfile(phpspec_configuration_file):
                debug_message('found file \'%s\'', phpspec_configuration_file)
                debug_message('found relative file \'%s\'', phpspec_configuration_file)
                return phpspec_configuration_file

    debug_message('not found')

    return None


def find_phpspec_working_directory(file_name, folders):
    configuration_file = find_phpspec_configuration_file(file_name, folders)
    if configuration_file:
        return os.path.dirname(configuration_file)


def is_valid_php_identifier(string):
    return re.match('^[a-zA-Z_][a-zA-Z0-9_]*$', string)


def has_test_spec(view):
    """Return True if the view contains a valid PHPSpec test spec."""
    for php_class in find_php_classes(view):
        if php_class[-4:] == 'Spec':
            return True
    return False


def find_php_classes(view, with_namespace=False):
    """Return list of class names defined in the view."""
    classes = []

    namespace = None
    for namespace_region in view.find_by_selector('source.php entity.name.namespace'):
        namespace = view.substr(namespace_region)
        break

    for class_as_region in view.find_by_selector('source.php entity.name.class - meta.use'):
        class_as_string = view.substr(class_as_region)
        if is_valid_php_identifier(class_as_string):
            if with_namespace:
                classes.append({
                    'namespace': namespace,
                    'class': class_as_string
                })
            else:
                classes.append(class_as_string)

    # BC: < 3114
    if not classes:  # pragma: no cover
        for class_as_region in view.find_by_selector('source.php entity.name.type.class - meta.use'):
            class_as_string = view.substr(class_as_region)
            if is_valid_php_identifier(class_as_string):
                classes.append(class_as_string)

    return classes

def find_line_number_from_row(view, region):
    (row, col) = view.rowcol(region.begin())
    return row + 1

def find_line_number(view):
    """
    Return a list of selected test method names.

    Return an empty list if no selections found.

    Selection can be anywhere inside one or more test methods.
    """
    method_names = []
    line_number = ''

    function_regions = view.find_by_selector('entity.name.function')
    function_areas = []
    # Only include areas that contain function declarations.
    for function_area in view.find_by_selector('meta.function'):
        for function_region in function_regions:
            if function_region.intersects(function_area):
                function_areas.append(function_area)

    for region in view.sel():
        for i, area in enumerate(function_areas):
            if not area.a <= region.a <= area.b:
                continue

            if i not in function_regions and not area.intersects(function_regions[i]):
                continue

            word = view.substr(function_regions[i])
            if is_valid_php_identifier(word):
                method_names.append(word)
                line_number = find_line_number_from_row(view, function_regions[i])
            break

    # BC: < 3114
    if not method_names:  # pragma: no cover
        for region in view.sel():
            word_region = view.word(region)
            word = view.substr(word_region)
            if not is_valid_php_identifier(word):
                return []

            scope_score = view.score_selector(word_region.begin(), 'entity.name.function.php')
            if scope_score > 0:
                method_names.append(word)
                line_number = find_line_number_from_row(view, word_region)
            else:
                return []

    ignore_methods = ['setup', 'teardown']

    return line_number
    # return [m for m in method_names if m.lower() not in ignore_methods]


class ShowInPanel:
    def __init__(self, window):
        self.window = window

    def display_results(self):
        self.panel = self.window.get_output_panel("exec")
        self.window.run_command("show_panel", {"panel": "output.exec"})

        self.panel.settings().set("color_scheme", SPU_THEME)
        self.panel.set_syntax_file(SPU_SYNTAX)

class Switchable:

    def __init__(self, location):
        self.location = location
        self.file = location[0]

    def file_encoded_position(self, view):
        window = view.window()

        file = self.location[0]
        row = self.location[2][0]
        col = self.location[2][1]

        # If the file we're switching to is already open,
        # then by default don't goto encoded position.
        for v in window.views():
            if v.file_name() == self.location[0]:
                row = None
                col = None

        # If cursor is on a symbol like a class method,
        # then try find the relating test method or vice-versa,
        # and use that as the encoded position to jump to.
        symbol = view.substr(view.word(view.sel()[0].b))
        if symbol:
            if symbol[:4] == 'test':
                symbol = symbol[4:]
                symbol = symbol[0].lower() + symbol[1:]
            else:
                symbol = 'test' + symbol[0].upper() + symbol[1:]

            locations = window.lookup_symbol_in_open_files(symbol)
            if locations:
                for location in locations:
                    if location[0] == self.location[0]:
                        row = location[2][0]
                        col = location[2][1]
                        break

        encoded_postion = ''
        if row:
            encoded_postion += ':' + str(row)
        if col:
            encoded_postion += ':' + str(col)

        return file + encoded_postion


def refine_switchable_locations(locations, file):
    debug_message('refine location')
    if not file:
        return locations, False

    debug_message('file=%s', file)
    debug_message('locations=%s', locations)

    files = []
    if file.endswith('Spec.php'):
        file_is_test_spec = True
        file = file.replace('Spec.php', '.php')
        files.append(re.sub('(\\/)?[sS]pec\\/?', '/', file))
        files.append(re.sub('(\\/)?[sS]pec\\/', '/src/', file))
    else:
        file_is_test_spec = False
        file = file.replace('.php', 'Spec.php')
        files.append(file)
        files.append(re.sub('(\\/)?src\\/', '/', file))
        files.append(re.sub('(\\/)?src\\/', '/test/', file))

    debug_message('files=%s', files)

    if len(locations) > 1:
        common_prefix = os.path.commonprefix([l[0] for l in locations])
        if common_prefix != '/':
            files = [file.replace(common_prefix, '') for file in files]

    for location in locations:
        loc_file = location[0]
        if not file_is_test_spec:
            loc_file = re.sub('\\/[sS]pec\\/?', '/', loc_file)

        for file in files:
            if loc_file.endswith(file):
                return [location], True

    return locations, False


def find_switchable(view, on_select=None):
    # Args:
    #   view (View)
    #   on_select (callable)
    #
    # Returns:
    #   void
    window = view.window()

    if on_select is None:
        raise ValueError('a callable is required')

    file = view.file_name()
    debug_message('file=%s', file)

    classes = find_php_classes(view, with_namespace=True)
    if len(classes) == 0:
        return message_dialog('PHPSpec\n\nCould not find a test spec or class under test.')

    debug_message('file contains %s class %s', len(classes), classes)

    locations = []
    for _class in classes:
        class_name = _class['class']

        if class_name[-4:] == 'Spec':
            symbol = class_name[:-4]
        else:
            symbol = class_name + 'Spec'

        symbol_locations = window.lookup_symbol_in_index(symbol)
        locations += symbol_locations

    debug_message('class has %s location %s', len(locations), locations)

    def unique_locations(locations):
        locs = []
        seen = set()
        for location in locations:
            if location[0] not in seen:
                seen.add(location[0])
                locs.append(location)

        return locs

    locations = unique_locations(locations)

    if len(locations) == 0:
        if has_test_spec(view):
            return message_dialog('PHPSpec\n\nCould not find class under test.')
        else:
            return message_dialog('PHPSpec\n\nCould not test spec.')

    def _on_select(index):
        if index == -1:
            return

        switchable = Switchable(locations[index])

        if on_select is not None:
            on_select(switchable)

    locations, is_exact = refine_switchable_locations(locations=locations, file=file)

    debug_message('is_exact=%s', is_exact)
    debug_message('locations(%s)=%s', len(locations), locations)

    if is_exact and len(locations) == 1:
        return _on_select(0)

    window.show_quick_panel(['{}:{}'.format(l[1], l[2][0]) for l in locations], _on_select)


def put_views_side_by_side(view_a, view_b):
    if view_a == view_b:
        return

    window = view_a.window()

    if window.num_groups() == 1:
        window.run_command('set_layout', {
            "cols": [0.0, 0.5, 1.0],
            "rows": [0.0, 1.0],
            "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]
        })

    view_a_index = window.get_view_index(view_a)
    view_b_index = window.get_view_index(view_b)

    if window.num_groups() <= 2 and view_a_index[0] == view_b_index[0]:

        if view_a_index[0] == 0:
            window.set_view_index(view_b, 1, 0)
        else:
            window.set_view_index(view_b, 0, 0)

        # Ensure focus is not lost from either view.
        window.focus_view(view_a)
        window.focus_view(view_b)


def exec_file_regex():
    if platform() == 'windows':
        return '((?:[a-zA-Z]\\:)?\\\\[a-zA-Z0-9 \\.\\/\\\\_-]+)(?: on line |\\:)([0-9]+)'
    else:
        return '(\\/[a-zA-Z0-9 \\.\\/_-]+)(?: on line |\\:)([0-9]+)'


def is_file_executable(file):
    return os.path.isfile(file) and os.access(file, os.X_OK)


def is_valid_php_version_file_version(version):
    return bool(re.match(
        '^(?:master|[1-9]\\.[0-9]+(?:snapshot|\\.[0-9]+(?:snapshot)?)|[1-9]\\.x|[1-9]\\.[0-9]+\\.x)$',
        version
    ))


def build_cmd_options(options, cmd):
    for k, v in options.items():
        if v:
            if len(k) == 1:
                if isinstance(v, list):
                    for _v in v:
                        cmd.append('-' + k)
                        cmd.append(_v)
                else:
                    cmd.append('-' + k)
                    if v is not True:
                        cmd.append(v)
            else:
                cmd.append('--' + k)
                if v is not True:
                    cmd.append(v)

    return cmd


def build_filter_option_pattern(list):
    return '::(' + '|'.join(sorted(list)) + ')( with data set .+)?$'


def filter_path(path):
    return os.path.expandvars(os.path.expanduser(path))


def _get_phpspec_executable(working_dir, include_composer_vendor_dir=True):
    if include_composer_vendor_dir:
        if platform() == 'windows':
            composer_phpspec_executable = os.path.join(working_dir, os.path.join('vendor', 'bin', 'phpspec-run.bat'))
        else:
            composer_phpspec_executable = os.path.join(working_dir, os.path.join('vendor', 'bin', 'phpspec'))

        if is_file_executable(composer_phpspec_executable):
            return composer_phpspec_executable

    executable = shutil.which('phpspec')
    if executable:
        return executable
    else:
        raise ValueError('phpspec not found')

def _get_winry_executable(working_dir, user_winry=False):
    if user_winry:
        winry_executable = os.path.join(
            working_dir,
            os.path.join('winry')
        )

        if is_file_executable(winry_executable):
            return winry_executable
        else:
            raise ValueError('winry not found')
    else:
        return None

def _get_php_executable(working_dir, php_versions_path, php_executable=None):
    php_version_file = os.path.join(working_dir, '.php-version')
    if os.path.isfile(php_version_file):
        with open(php_version_file, 'r') as f:
            php_version_number = f.read().strip()

        if not is_valid_php_version_file_version(php_version_number):
            raise ValueError("'%s' file contents is not a valid version number" % php_version_file)

        if not php_versions_path:
            raise ValueError("'phpspec-run.php_versions_path' is not set")

        php_versions_path = filter_path(php_versions_path)
        if not os.path.isdir(php_versions_path):
            raise ValueError("'phpspec-run.php_versions_path' '%s' does not exist or is not a valid directory" % php_versions_path)  # noqa: E501

        if platform() == 'windows':
            php_executable = os.path.join(php_versions_path, php_version_number, 'php.exe')
        else:
            php_executable = os.path.join(php_versions_path, php_version_number, 'bin', 'php')

        if not is_file_executable(php_executable):
            raise ValueError("php executable '%s' is not an executable file" % php_executable)

        return php_executable

    if php_executable:
        php_executable = filter_path(php_executable)
        if not is_file_executable(php_executable):
            raise ValueError("'phpspec-run.php_executable' '%s' is not an executable file" % php_executable)

        return php_executable


class PHPSpecRun():

    def __init__(self, window):
        self.window = window
        self.view = self.window.active_view()
        if not self.view:
            raise ValueError('view not found')

        debug_message('view %d %s', self.view.id(), self.view.file_name())

    def run(self, working_dir=None, file=None, options=None, line_number=None, directory=None):
        debug_message('phpspec run with working_dir=%s, file=%s, line_number=%s, directory=%s, options=%s', working_dir, file, line_number, directory, options)

        # Kill any currently running tests
        self.window.run_command('exec', {'kill': True})

        env = {}
        cmd = []
        original_file = ''

        try:
            if not working_dir:
                working_dir = find_phpspec_working_directory(self.view.file_name(), self.window.folders())
                if not working_dir:
                    raise ValueError('working directory not found')

            if not os.path.isdir(working_dir):
                raise ValueError('working directory does not exist or is not a valid directory')

            debug_message('working dir \'%s\'', working_dir)


            winry_executable = self.get_winry_executable(working_dir)

            if winry_executable:
                cmd.append(winry_executable)
                cmd.append('phpspec')
            else:
                php_executable = self.get_php_executable(working_dir)
                if php_executable:
                    env['PATH'] = os.path.dirname(php_executable) + os.pathsep + os.environ['PATH']
                    debug_message('php executable = %s', php_executable)

                phpspec_executable = self.get_phpspec_executable(working_dir)
                cmd.append(phpspec_executable)
                debug_message('executable \'%s\'', phpspec_executable)

            options = self.filter_options(options)
            debug_message('options %s', options)

            cmd.append('run')
            cmd = build_cmd_options(options, cmd)

            if file:
                if os.path.isfile(file):
                    file = os.path.relpath(file, working_dir)
                    original_file = file
                    if line_number:
                        file+= ':' + str(line_number)
                    elif directory:
                        file = os.path.dirname(file)
                    cmd.append(file)
                    debug_message('file %s', file)
                else:
                    raise ValueError('test file \'%s\' not found' % file)

        except ValueError as e:
            status_message('PHPSpec Run: {}'.format(e))
            print('PHPSpec Run: {}'.format(e))
            return
        except Exception as e:
            status_message('PHPSpec Run: {}'.format(e))
            print('PHPSpec Run: \'{}\''.format(e))
            raise e

        debug_message('env %s', env)
        debug_message('cmd %s', cmd)

        if self.view.settings().get('phpspec-run.save_all_on_run'):
            # Write out every buffer in active
            # window that has changes and is
            # a real file on disk.
            for view in self.window.views():
                if view.is_dirty() and view.file_name():
                    view.run_command('save')

        if self.view.settings().get('phpspec-run.suffix'):
            cmd.append(self.view.settings().get('phpspec-run.suffix'))

        phpspec_configuration_file = find_phpspec_configuration_file(self.view.file_name(), self.window.folders())

        relative_phpspec_configuration_file = file = os.path.relpath(phpspec_configuration_file, working_dir)

        cmd.append('--config=' + relative_phpspec_configuration_file)

        debug_message('****** cmd \'%s\'', cmd)

        self.window.run_command('exec', {
            'env': env,
            'cmd': cmd,
            'file_regex': exec_file_regex(),
            'quiet': not is_debug(self.view),
            'shell': False,
            'syntax': 'Packages/{}/res/text-ui-result.sublime-syntax'.format(__name__.split('.')[0]),
            'word_wrap': False,
            'working_dir': working_dir
        })

        set_window_setting('phpspec-run._test_last', {
            'options': options,
            'file': original_file,
            'directory': directory,
            'working_dir': working_dir,
            'line_number': line_number
        }, window=self.window)

        panel = self.window.create_output_panel('exec')
        panel_settings = panel.settings()
        panel_settings.set('rulers', [])

        if self.view.settings().has('phpspec-run.text_ui_result_font_size'):
            panel_settings.set(
                'font_size',
                self.view.settings().get('phpspec-run.text_ui_result_font_size')
            )

        color_scheme = self.get_auto_generated_color_scheme()
        panel_settings.set('color_scheme', color_scheme)
        self.window.run_command("show_panel", {"panel": "output.exec"})

    def run_previous(self):
        kwargs = get_window_setting('phpspec-run._test_last', window=self.window)
        debug_message('run last %s', kwargs)
        if kwargs:
            self.run(**kwargs)
        else:
            return status_message('PHPSpec Run: no tests were run so far')

    def run_spec(self):
        file = self.view.file_name()
        debug_message('run file %s', file)
        if file:
            if has_test_spec(self.view):
                self.run(file=file)
            else:
                find_switchable(self.view, on_select=lambda switchable: self.run(file=switchable.file))
        else:
            return status_message('PHPSpec Run: not a test file')

    def run_directory(self):
        file = self.view.file_name()
        directory = 'Yes'
        debug_message('run file %s', file)
        if file:
            if has_test_spec(self.view):
                self.run(file=file, directory=directory)
            else:
                find_switchable(self.view, on_select=lambda switchable: self.run(file=switchable.file))
        else:
            return status_message('PHPSpec Run: not a spec directory')

    def run_here(self):
        debug_message('run here')
        if has_test_spec(self.view):
            file = self.view.file_name()
            options = {}
            line_number = find_line_number(self.view)
            if line_number:
                debug_message('Line number: \'%s\'', line_number)

            self.run(file=file, line_number=line_number)

        else:
            find_switchable(self.view, on_select=lambda switchable: self.run(file=switchable.file))

    def show_results(self):
        self.window.run_command('show_panel', {'panel': 'output.exec'})

    def cancel(self):
        self.window.run_command('exec', {'kill': True})

    def toggle_option(self, option):
        options = get_window_setting('phpspec-run.options', default={}, window=self.window)
        options[option] = not bool(options[option]) if option in options else True
        set_window_setting('phpspec-run.options', options, window=self.window)

    def filter_options(self, options):
        if options is None:
            options = {}

        window_options = get_window_setting('phpspec-run.options', default={}, window=self.window)
        if window_options:
            for k, v in window_options.items():
                if k not in options:
                    options[k] = v

        view_options = self.view.settings().get('phpspec-run.options')
        if view_options:
            for k, v in view_options.items():
                if k not in options:
                    options[k] = v

        return options

    def get_php_executable(self, working_dir):
        versions_path = self.view.settings().get('phpspec-run.php_versions_path')
        executable = self.view.settings().get('phpspec-run.php_executable')

        return _get_php_executable(working_dir, versions_path, executable)

    def get_phpspec_executable(self, working_dir):
        composer = self.view.settings().get('phpspec-run.composer')

        return _get_phpspec_executable(working_dir, composer)

    def get_winry_executable(self, working_dir):
        winry = self.view.settings().get('phpspec-run.winry')

        return _get_winry_executable(working_dir, winry)

    def get_auto_generated_color_scheme(self):
        color_scheme = self.view.settings().get('color_scheme')
        debug_message('checking if color scheme \'{}\' needs support'.format(color_scheme))

        if color_scheme.endswith('.sublime-color-scheme'):
            return color_scheme

        try:
            # Try to patch color scheme with default test result colors

            color_scheme_resource = load_resource(color_scheme)
            if 'phpspecrun' in color_scheme_resource or 'phpspec-run' in color_scheme_resource:
                debug_message('color scheme has plugin support')
                return color_scheme

            if 'region.greenish' in color_scheme_resource:
                debug_message('color scheme has region colorish support')
                return color_scheme

            cs_head, cs_tail = os.path.split(color_scheme)
            cs_package = os.path.split(cs_head)[1]
            cs_name = os.path.splitext(cs_tail)[0]

            file_name = cs_package + '__' + cs_name + '.hidden-tmTheme'
            abs_file = os.path.join(cache_path(), __name__.split('.')[0], 'color-schemes', file_name)
            rel_file = 'Cache/{}/color-schemes/{}'.format(__name__.split('.')[0], file_name)

            debug_message('auto generated color scheme = %s', rel_file)

            if not os.path.exists(os.path.dirname(abs_file)):
                os.makedirs(os.path.dirname(abs_file))

            color_scheme_resource_partial = load_resource(
                'Packages/{}/res/text-ui-result-theme-partial.txt'.format(__name__.split('.')[0]))

            with open(abs_file, 'w', encoding='utf8') as f:
                f.write(re.sub(
                    '</array>\\s*'
                    '((<!--\\s*)?<key>.*</key>\\s*<string>[^<]*</string>\\s*(-->\\s*)?)*'
                    '</dict>\\s*</plist>\\s*'
                    '$',

                    color_scheme_resource_partial + '\\n</array></dict></plist>',
                    color_scheme_resource
                ))

            return rel_file
        except Exception as e:
            print('PHPSpec Run: an error occurred trying to patch color'
                  ' scheme with PHPSpec test results colors: {}'.format(str(e)))

            return color_scheme


class PhpspecRunSuiteCommand(sublime_plugin.WindowCommand):

    def run(self):
        PHPSpecRun(self.window).run()


class PhpspecRunDirectoryCommand(sublime_plugin.WindowCommand):

    def run(self):
        PHPSpecRun(self.window).run_directory()


class PhpspecRunSpecCommand(sublime_plugin.WindowCommand):

    def run(self):
        PHPSpecRun(self.window).run_spec()


class PhpspecRunPreviousCommand(sublime_plugin.WindowCommand):

    def run(self):
        PHPSpecRun(self.window).run_previous()


class PhpspecRunHereCommand(sublime_plugin.WindowCommand):

    def run(self):
        PHPSpecRun(self.window).run_here()


class PhpspecRunResultsCommand(sublime_plugin.WindowCommand):

    def run(self):
        PHPSpecRun(self.window).show_results()


class PhpspecRunCancelCommand(sublime_plugin.WindowCommand):

    def run(self):
        PHPSpecRun(self.window).cancel()

class PhpspecRunToggleOptionCommand(sublime_plugin.WindowCommand):

    def run(self, option):
        PHPSpecRun(self.window).toggle_option(option)
