from .github import GitHubAccount
from .. import parameter_container as pc
from .. import github_logger
from .utils import get_issue_post, compare_issues, restock, show_stock
from .utils import format_issue, format_comment, find_comment_region, find_list_region
import sublime
import threading
import json


class IssueObj:
    def __init__(self, settings, username=None, repo_name=None):
        self.github_account = GitHubAccount(settings)
        self.repo_name = repo_name
        self.username = username
        self.issue_response = None
        self.total_page_number = 1
        self.current_page_number = 1
        self.links = None

    def get_repo(self, username, repo_name):
        self.username = username
        self.repo_name = repo_name

    def find_repo(self, view, repo_storage):
        view_id = view.id()
        try:
            github_logger.info("found the view in repo_dictionary")
            self.username, self.repo_name = show_stock(repo_storage, view_id)
        except:
            raise Exception("Which repository should I post?")

    def get(self, issue_url=None, **params):
        if not issue_url:
            issue_url = self.github_account.join_issue_url(
                username=self.username, repo_name=self.repo_name)
        self.issue_response = self.github_account.session.get(issue_url, **
                                                              params)
        return self.issue_response

    def get_links(self):
        if not self.issue_response:
            self.get()
        return self.issue_response.links

    def post_issue(self, **params):
        issue_url = self.github_account.join_issue_url(
            username=self.username, repo_name=self.repo_name)
        return self.github_account.session.post(issue_url, **params)

    def update_issue(self, issue_number, **params):
        issue_url = self.github_account.join_issue_url(
            username=self.username,
            repo_name=self.repo_name,
            issue_number=str(issue_number))
        return self.github_account.session.patch(issue_url, **params)

    def post_comment(self, issue_number, **params):
        issue_url = self.github_account.join_issue_url(
            username=self.username,
            repo_name=self.repo_name,
            issue_number=str(issue_number))
        return self.github_account.session.post(issue_url + '/comments',
                                                **params)

    def update_comment(self, comment_id, **params):
        issue_url = self.github_account.join_issue_url(
            username=self.username, repo_name=self.repo_name)
        return self.github_account.session.patch(
            issue_url + '/comments/' + str(comment_id), **params)

    def delete_comment(self, comment_id, **params):
        issue_url = self.github_account.join_issue_url(
            username=self.username, repo_name=self.repo_name)
        return self.github_account.session.delete(
            issue_url + '/comments/' + str(comment_id), **params)

    def get_issue(self, issue_number, **params):
        issue_url = self.github_account.join_issue_url(
            username=self.username,
            repo_name=self.repo_name,
            issue_number=str(issue_number))
        return (
            self.github_account.session.get(issue_url, **params),
            self.github_account.session.get(issue_url + '/comments', **params))


class PrintListInView(threading.Thread):
    def __init__(self, view, issue_list, repo_storage, command=None, **args):
        super(PrintListInView, self).__init__(self)
        self.issue_list = issue_list
        self.args = args
        self.repo_storage = repo_storage
        self.view = view
        self.command = command

    def run(self):
        if not self.issue_list.issue_response:
            self.issue_list.get(params=self.args)
        else:
            if self.command:
                links = self.issue_list.get_links()
                if self.command in links:
                    self.issue_list.get(links[self.command]['url'], params=self.args)
                else:
                    pass
        issue_response = self.issue_list.issue_response
        if issue_response.status_code in (200, 201):
            json_list = issue_response.json()
            snippet = '\n'
            for issue in json_list:
                snippet += "{:<12}{:<10}{}".format(
                    str(issue['number']), issue['locked'],
                    issue['title']) + pc.line_ends
            start_point, end_point = find_list_region(self.view)
            self.view.run_command("replace_snippet",
                                  {"snippet": snippet,
                                   "start_point": start_point,
                                   "end_point": end_point})
            restock(self.repo_storage, self.view.id(),
                    (self.issue_list.username, self.issue_list.repo_name))
        else:
            sublime.status_message("Cannot obtain issue list, error code {}".
                                   format(str(issue_response.status_code)))


class PrintIssueInView(threading.Thread):
    def __init__(self,
                 issue_list,
                 issue_number,
                 issue_storage,
                 repo_info,
                 repo_info_storage,
                 view=None):
        super(PrintIssueInView, self).__init__(self)
        self.issue_list = issue_list
        self.issue_number = issue_number
        self.issue_storage = issue_storage
        self.repo_info = repo_info
        self.repo_info_storage = repo_info_storage
        self.view = view

    def run(self):
        issue_response, comments_response = self.issue_list.get_issue(
            self.issue_number)
        if issue_response.status_code in (200, 201):
            issue = issue_response.json()
            comments = comments_response.json()
            snippet = ''
            snippet += format_issue(issue)
            comment_dict = {}
            for comment in comments:
                comment_dict[comment['id']] = comment
                snippet += format_comment(comment)
            snippet += "## Add New Comment:" + pc.line_ends
            snippet += pc.line_ends
            snippet += "*" + "-" * 10 + "END" + '-' * 10 + "*"
            if not self.view:
                self.view = sublime.active_window().new_file()
            restock(self.issue_storage, self.view.id(),
                    {"issue": issue,
                     "comments": comment_dict})
            restock(self.repo_info_storage, self.view.id(), self.repo_info)
            self.view.run_command("erase_snippet")
            self.view.run_command("set_file_type", {"syntax": pc.issue_syntax})
            self.view.run_command("insert_issue_snippet", {"snippet": snippet})
            self.view.set_scratch(True)


class IssueManipulate(threading.Thread):
    def __init__(self, view=None, issue_storage=None, issue_list=None):
        super(IssueManipulate, self).__init__(self)
        if not view:
            self.view = sublime.active_window().active_view()
        else:
            self.view = view
        self.issue_storage = issue_storage
        self.issue_list = issue_list


class PostNewIssue(IssueManipulate):
    def run(self):
        issue_post = get_issue_post(self.view)
        github_logger.info("preparing updating issue " + str(issue_post[
            'issue']))
        post_result = self.issue_list.post_issue(
            data=json.dumps(issue_post['issue']))
        if post_result.status_code in (200, 201):
            sublime.status_message("Issue Posted")
            if self.issue_storage:
                restock(self.issue_storage, self.view.id(),
                        {'issue': post_result.json(),
                         'comments': {}})
            issue = post_result.json()
            snippet = format_issue(issue)
            github_logger.info("format issue")
            snippet += "## Add New Comment:" + pc.line_ends
            snippet += pc.line_ends
            snippet += "*" + "-" * 10 + "END" + '-' * 10 + "*"
            self.view.run_command("erase_snippet")
            self.view.run_command("set_file_type", {"syntax": pc.issue_syntax})
            self.view.run_command("insert_issue_snippet", {"snippet": snippet})
            github_logger.info("set syntax")
            self.view.run_command(
                "insert_issue_snippet",
                {"start_point": self.view.size(),
                 "snippet": "\n*<Issue number {} created at {}>*".format(
                     str(post_result.json()['id']),
                     post_result.json()['created_at'])})
        else:
            sublime.status_message(
                "Issue not Posted, error code {} please try again.".format(
                    str(post_result.status_code)))


class UpdateIssue(IssueManipulate):
    def run(self):
        view_id = self.view.id()
        original_issue = show_stock(self.issue_storage, view_id)
        last_updated_time = original_issue['issue']['updated_at']
        modified_issue = get_issue_post(self.view)
        issue_change, comment_change, deleted_comments = compare_issues(
            original_issue, modified_issue)
        if issue_change:
            updating_issue = self.issue_list.update_issue(
                original_issue['issue']['number'],
                data=json.dumps(issue_change))
            if updating_issue.status_code in (200, 201):
                sublime.status_message("Issue updated")
                original_issue['issue'] = updating_issue.json()
                if updating_issue.json()['updated_at'] != last_updated_time:
                    self.view.run_command(
                        "insert_issue_snippet",
                        {"start_point": self.view.size(),
                         "snippet":
                         "\n*<Issue number {} updated at {}>*".format(
                             str(updating_issue.json()['id']),
                             updating_issue.json()['updated_at'])})
            else:
                sublime.status_message("Issue update fails")
                github_logger.info("issue update fails, error code " + str(
                    updating_issue.status_code))
        if comment_change:
            for comment_id, content in comment_change.items():
                updating_comment = self.issue_list.update_comment(
                    comment_id=comment_id, data=json.dumps({'body': content}))
                if updating_comment.status_code in (200, 201):
                    sublime.status_message("Comment updated")
                    original_issue["comments"][
                        comment_id] = updating_comment.json()
                    self.view.run_command(
                        "insert_issue_snippet",
                        {"start_point": self.view.size(),
                         "snippet": "\n*<Comment ID {} updated at {}>*".format(
                             str(comment_id),
                             updating_comment.json()['updated_at'])})
                else:
                    sublime.status_message("Comment update fails")
                    github_logger.info("issue update fails, error code " + str(
                        updating_comment.status_code))
        if deleted_comments:
            for comment_id in deleted_comments:
                deleted_comment = self.issue_list.delete_comment(
                    comment_id=comment_id)
                if deleted_comment.status_code == 204:
                    del original_issue["comments"][comment_id]
                    sublime.status_message("Comment deleted.")
                    self.view.run_command("insert_issue_snippet", {
                        "start_point": self.view.size(),
                        "snippet":
                        "\n*<Comment ID {} deleted.>*".format(str(comment_id))
                    })
                else:
                    sublime.status_message("Fail to delete comment!")
        if modified_issue['new_comment']:
            new_comment = self.issue_list.post_comment(
                modified_issue['issue']['number'],
                data=json.dumps({'body': modified_issue['new_comment']}))
            if new_comment.status_code in (200, 201):
                sublime.status_message("Comment Posted")
                original_issue["comments"][new_comment.json()[
                    'id']] = new_comment.json()
                snippet = format_comment(new_comment.json())
                snippet += "## Add New Comment:" + pc.line_ends
                snippet += pc.line_ends
                snippet += "*" + "-" * 10 + "END" + '-' * 10 + "*"
                a, b = find_comment_region(self.view)
                self.view.run_command("replace_snippet", {"start_point": a,
                                                          "end_point": b,
                                                          "snippet": snippet})
                self.view.run_command(
                    "insert_issue_snippet",
                    {"start_point": self.view.size(),
                     "snippet": "\n*<Comment ID {} created at {}>*".format(
                         str(new_comment.json()['id']),
                         new_comment.json()['created_at'])})
                comment_id = new_comment.json()['id']
                github_logger.info("new comment id is " + str(comment_id))

            else:
                sublime.status_message("Comment post fails")
                github_logger.info("comment post fails, error code " + str(
                    new_comment.status_code))
        restock(self.issue_storage, view_id, original_issue)
