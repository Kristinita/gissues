import sublime
import sublime_plugin
from .libgit import issue
from .libgit import utils
from .libgit import github
from . import parameter_container as pc
from . import flag_container as fc
from . import log
from . import repo_info_storage, issue_obj_storage
import re
from queue import Queue
from functools import partial

active_issue_obj = None


def plugin_loaded():
    global active_issue_obj
    settings = sublime.load_settings("github_issue.sublime-settings")
    pc.read_settings(settings)
    system_setting = sublime.load_settings("Preferences.sublime-settings")
    custom_trigger = [{
        "characters": "@",
        "selector": "text.html.github.issue"
    }, {
        "characters": "#",
        "selector": "text.html.github.issue"
    }, {
        "characters": pc.commit_completion_trigger,
        "selector": "text.html.github.issue"
    }]
    auto_complete_trigger = system_setting.get("auto_complete_triggers")
    if auto_complete_trigger:
        auto_complete_trigger.extend(custom_trigger)
    else:
        auto_complete_trigger = custom_trigger
    system_setting.set("auto_complete_triggers", auto_complete_trigger)

    pc.line_ends = "\n"
    log("debug level is {}".format(str(pc.debug_flag)))
    active_issue_obj = issue.IssueObj(settings)


class ChangeIssuePageCommand(sublime_plugin.TextCommand):
    def is_enabled(self):
        syntax_name = self.view.settings().get('syntax')
        if syntax_name == pc.list_syntax:
            return True
        return False

    def run(self, edit, command):
        global active_issue_obj
        log("we have the command {}".format(command))
        view_text = "_{}_".format(command.capitalize())
        log("we are matching {}".format(view_text))
        for flag in fc.pagination_flags.keys():
            fc.pagination_flags[flag] = False
            log("{} set to False".format(flag))
            if flag == view_text:
                log("flag matches, set {} to True".format(flag))
                fc.pagination_flags[flag] = True
        print_next_page_issues = issue.PrintListInView(
            self.view, active_issue_obj, repo_info_storage, command, False)
        print_next_page_issues.start()


class ShowGithubIssueListCommand(sublime_plugin.WindowCommand):
    def run(self, **args):
        repo_loader = LoadRepoList()
        repo_loader.format_entries()
        log("I am showing the issue list!")
        repo_loader.show_panel_then_print_list(**args)


class ShowGithubIssueCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        current_view = sublime.active_window().active_view()
        syntax_name = current_view.settings().get('syntax')
        if syntax_name == pc.list_syntax:
            return True
        return False

    def run(self):
        global active_issue_obj
        view = sublime.active_window().active_view()
        target_line = view.substr(view.line(view.sel()[0]))
        match_id = re.search(r'^\d+(?=\s)', target_line)
        issue_number = int(match_id.group(0))
        try:
            active_issue_obj.find_repo(view, repo_info_storage)
            repo_info = (active_issue_obj.username, active_issue_obj.repo_name,
                         None)
            print_in_view = issue.PrintIssueInView(
                active_issue_obj, issue_number, issue_obj_storage, repo_info,
                repo_info_storage)
            print_in_view.start()
        except:
            # repo_info_storage.put(repo_info_dictionary)
            raise Exception("Cannot find repo information!")


class NewGithubIssueCommand(sublime_plugin.WindowCommand):
    def run(self):
        repo_loader = LoadRepoList()
        repo_loader.format_entries()
        repo_loader.show_panel_then_create_issue()


class PostGithubIssueCommand(sublime_plugin.WindowCommand):
    def run(self):
        global active_issue_obj
        self.view = sublime.active_window().active_view()
        active_issue_obj.find_repo(self.view, repo_info_storage)
        post_issue = issue.PostNewIssue(
            issue_list=active_issue_obj, issue_storage=issue_obj_storage)
        post_issue.start()


class UpdateGithubIssueCommand(sublime_plugin.WindowCommand):
    def run(self):
        global active_issue_obj
        self.view = sublime.active_window().active_view()
        if not repo_info_storage.empty():
            active_issue_obj.find_repo(self.view, repo_info_storage)
        else:
            raise Exception("Error in obtaining Repo Info!")
        update_issue = issue.UpdateIssue(
            issue_list=active_issue_obj, issue_storage=issue_obj_storage)
        update_issue.start()


class LoadRepoList:
    def __init__(self):
        self.username = None
        self.repo_name = None
        self.window = sublime.active_window()
        self.entries = None

    def format_entries(self):
        repo_list = []
        folder_list = sublime.active_window().folders()
        if folder_list:
            for folder_path in folder_list:
                repo_info = github.get_github_repo_info(folder_path)
                if repo_info != (-1, -1):
                    repo_list.append(repo_info)
        entries = ["manually enter repository..."]
        entries.extend(
            ["{}/{}".format(repo[0], repo[1]) for repo in repo_list])
        self.entries = entries

    def show_panel_then_print_list(self, **args):
        _param_on_repo_selection = partial(
            self.on_repo_selection,
            subsequent_action=self.print_issue_list,
            **args)
        self.window.show_quick_panel(self.entries, _param_on_repo_selection)

    def show_panel_then_create_issue(self):
        _param_on_repo_selection = partial(
            self.on_repo_selection, subsequent_action=self.create_issue)

        self.window.show_quick_panel(self.entries, _param_on_repo_selection)

    def on_enter_repo_info(self, content, subsequent_action, **args):
        if '/' in content:
            self.username, self.repo_name = [x.strip()
                                             for x in content.split('/')]
            log("username is " + str(self.username))
            log("repo name is " + str(self.repo_name))
            acquire_repo_info = issue.AcquireRepoInfo(self.username,
                                                      self.repo_name)
            acquire_repo_info.start()
            subsequent_action(**args)
        else:
            raise Exception(
                "Please enter repo in the format username/repo_name")

    def on_repo_selection(self, selection, subsequent_action, **args):
        if selection >= 0:
            if selection == 0:
                self.window.run_command('hide_panel')
                _param_on_enter_repo_info = partial(
                    self.on_enter_repo_info,
                    subsequent_action=subsequent_action,
                    **args)
                content = sublime.get_clipboard(256)
                if content.count(
                        "/") == 1:  # Add a condition to try not to jerperdize irrelevant clipboard content
                    sublime.set_clipboard(content.strip())
                self.window.show_input_panel(
                    'Enter repo in the format username/repo_name:', '',
                    _param_on_enter_repo_info, None, None)
            else:
                self.username, self.repo_name = self.entries[selection].split(
                    '/')
                acquire_repo_info = issue.AcquireRepoInfo(self.username,
                                                          self.repo_name)
                acquire_repo_info.start()
                subsequent_action(**args)

    def print_issue_list(self, **args):
        global active_issue_obj
        active_issue_obj.get_repo(self.username, self.repo_name)
        issue_view = utils.print_list_framework()
        # acquire_list = issue.AcquireIssueTitle(active_issue_obj)
        # acquire_list.start()
        print_in_view = issue.PrintListInView(issue_view, active_issue_obj,
                                              repo_info_storage, **args)
        print_in_view.start()

    def create_issue(self):
        create_new_issue_view()
        view_id = sublime.active_window().active_view().id()
        utils.restock(repo_info_storage, view_id,
                      (self.username, self.repo_name, None))


def create_new_issue_view():
    snippet = ''
    snippet += "# Title         : " + pc.line_ends
    snippet += "## Label        : " + pc.line_ends
    snippet += "## Assignee     : " + pc.line_ends
    snippet += "*" + '-' * 10 + "Content" + '-' * 10 + "*" + pc.line_ends
    snippet += pc.line_ends
    snippet += "*" + '-' * 10 + "END" + '-' * 10 + "*" + pc.line_ends
    view = sublime.active_window().new_file()
    log("Create new view to write the issue")
    view.run_command("set_file_type", {"syntax": pc.issue_syntax})
    log("new issue will have a syntax {}".format(pc.issue_syntax))
    view.run_command("insert_issue_snippet", {"snippet": snippet})
    view.sel().clear()
    start_point = view.text_point(0, 18)
    view.sel().add(sublime.Region(start_point))
    view.show(start_point)
    view.set_encoding('UTF-8')
    log("insert a blank issue")
    view.set_scratch(True)


def find_line_ends():
    system_setting = sublime.load_settings("Preferences.sublime-settings").get(
        'default_line_ending')
    if system_setting != 'system':
        if system_setting == 'windows':
            return '\r\n'
        else:
            return '\n'
    else:
        if sublime.platform() == 'windows':
            return '\r\n'
        else:
            return '\n'
