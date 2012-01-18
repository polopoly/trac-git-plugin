# -*- coding: iso-8859-1 -*-
#
# Copyright (C) 2006,2008 Herbert Valerio Riedel <hvr@gnu.org>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

from trac.config import Option
from trac.core import *
from trac.util import TracError, shorten_line, escape
from trac.versioncontrol import Changeset, Node, Repository, \
                                IRepositoryConnector, NoSuchChangeset, NoSuchNode
from trac.wiki import IWikiSyntaxProvider
from trac.util.html import escape, html

import PyGIT

import sqlite

import re

class GitConnector(Component):
	implements(IRepositoryConnector, IWikiSyntaxProvider)

	lookup = Option('trac', 'svn_git_lookup_db', None,
				 """SVN -> GIT sqlite3 db. (''since 0.10-polopoly'')""")

	#######################
	# IWikiSyntaxProvider

	def get_wiki_syntax(self):
		yield (r'\b[0-9a-fA-F]{40,40}\b', 
		       lambda fmt, sha, match: self._format_sha_link(fmt, 'changeset', sha, sha))

		yield (r'\br[0-9]+\b',
		       lambda fmt, rev, match: self._format_rev_link(fmt, 'changeset', rev))

	def get_link_resolvers(self):
		yield ('sha', self._format_sha_link)
		yield ('rev', self._format_rev_link)

	def _format_sha_link(self, formatter, ns, sha, label, fullmatch=None):
		try:
			changeset = self.env.get_repository().get_changeset(sha)
			return html.a(label, class_="changeset",
				      title=shorten_line(changeset.message),
				      href=formatter.href.changeset(sha))
		except TracError, e:
			return html.a(label, class_="missing changeset",
				      href=formatter.href.changeset(sha),
				      title=unicode(e), rel="nofollow")

	def _format_rev_link(self, formatter, ns, rev):
		sha = self.env.get_repository().get_sha_from_rev(rev)
		if sha:
			return self._format_sha_link(formatter, 'changeset', sha, rev)
		else:
			return html.a(rev, class_="missing changeset",
				      href=formatter.href.changeset(rev), rel="nofollow")


	#######################
	# IRepositoryConnector

	def get_supported_types(self):
		yield ("git", 8)

    

	def get_repository(self, type, dir, authname):
		options = dict(self.config.options(type))
		return GitRepository(dir, self.lookup, self.log, options)

def split_branch_path(branch_and_path):
	if branch_and_path.startswith('RELENG-'):
		branch_end = branch_and_path.find('/')
		if branch_end == -1:
			return (branch_and_path, "")
		else:
			return (branch_and_path[0:branch_end], branch_and_path[branch_end:])
	return (None, branch_and_path)

class GitRepository(Repository):
	def __init__(self, path, lookup, log, options):
		self.gitrepo = path
		self.git = PyGIT.Storage(path)
		self.lookup = lookup
		Repository.__init__(self, "git:"+path, None, log)

	def get_sha_from_rev(self, rev):
		if self.lookup:
			if rev[0] == 'r':
				rev = rev[1:]
			conn  = sqlite.connect(self.lookup)
			cursor = conn.cursor()
			cursor.execute("select sha from lookup where rev = '%s'" % rev)
			found = None
			for row in cursor:
				found = row[0]
			cursor.close()
			conn.close()
			return found
		return None

	def get_youngest_rev(self):
		return "BRANCHES"

	def normalize_path(self, path):
		return path and path.strip('/') or ''

	def rev_or_sha(self, rev):
		if re.match("\b[0-9]{1,9}\b", rev):
			sha = self.get_sha_from_rev(rev)
			if sha:
				return sha
		return rev


	def normalize_rev(self, rev):
		if rev=='None' or rev == None or rev == '':
			return self.get_youngest_rev()
		normrev=self.git.verifyrev(self.rev_or_sha(rev))
		if normrev is None:
			raise NoSuchChangeset(rev)
		return normrev

	def short_rev(self, rev):
		return self.git.shortrev(self.normalize_rev(rev))

	def get_oldest_rev(self):
		return ""

	def get_node(self, branch_and_path, rev=None):
		(branch, path) = split_branch_path(branch_and_path.strip('/'))

		if rev and rev != "BRANCHES":
			return GitNode(self.git, self.log, path, branch, rev)
		if branch:
			return GitNode(self.git, self.log, path, branch, self.git.verifyrev(branch))
		return BranchNode(self.git, self.log)

	def get_changesets(self, start, stop):
		for rev in self.git.history_all(start, stop):
			yield self.get_changeset(rev)

	def get_changeset(self, rev):
		return GitChangeset(self.git, self.rev_or_sha(rev))

	def get_changes(self, old_path, old_rev, new_path, new_rev):
		if old_path != new_path:
			raise TracError("not supported in git_fs")

		for chg in self.git.diff_tree(old_rev, new_rev, self.normalize_path(new_path)):
			#print chg
			(mode1,mode2,obj1,obj2,action,path) = chg

			kind = Node.FILE
			if mode2.startswith('04') or mode1.startswith('04'):
				kind = Node.DIRECTORY

			if action == 'A':
				change = Changeset.ADD
			elif action == 'M':
				change = Changeset.EDIT
			elif action == 'D':
				change = Changeset.DELETE
			else:
				raise "OhOh"

			old_node = None
			new_node = None

			if change != Changeset.ADD:
				old_node = self.get_node(path, old_rev)
			if change != Changeset.DELETE:
				new_node = self.get_node(path, new_rev)

			yield (old_node, new_node, kind, change)

	def next_rev(self, rev, path=''):
		#print "next_rev"
		for c in self.git.children(rev):
			return c
		return None

	def previous_rev(self, rev):
		#print "previous_rev"
		for p in self.git.parents(rev):
			return p
		return None

	def rev_older_than(self, rev1, rev2):
		rc = self.git.rev_is_anchestor(rev1,rev2)
		#rc = rev1 in self.git.history(rev2, '', skip=1)
		return rc

	def sync(self):
		#print "GitRepository.sync"
		pass

class BranchNode(Node):
	def __init__(self, git, log, branch=None):
		self.log = log
		self.git = git
		self.rev = "BRANCHES"
		path = ""
		if branch:
			self.rev = self.git.verifyrev(branch)
			path = branch
		Node.__init__(self, path, self.rev, Node.DIRECTORY)

	def get_content(self):
		return None

	def get_properties(self):
		return {}

	def get_entries(self):
		if self.rev != "BRANCHES":
			for e in self.git.tree_ls(self.rev, ""):
				yield GitNode(self.git, self.log, "", self.rev, e)
		else:
			for branch in self.git.branches():
				yield BranchNode(self.git, self.log, branch)

	def get_content_type(self):
		return None

	def get_content_length(self):
		return None

	def get_history(self, limit=None):
		for rev in self.git.history(None, "", limit):
			yield (self.path, rev, Changeset.EDIT)

	def get_last_modified(self):
		return None


class GitNode(Node):
	def __init__(self, git, log, path, branch, rev, tree_ls_info=None):
		self.git = git
		self.log = log
		self.branch = branch
		self.sha = rev
		self.perm = None
		self.data_len = None

		kind = Node.DIRECTORY
		p = path.strip('/')
		if p != "":
                        if tree_ls_info == None or tree_ls_info == "":
				tree_ls_info = git.tree_ls(rev, p)
                                if tree_ls_info != []:
                                        [tree_ls_info] = tree_ls_info
                                else:
                                        tree_ls_info = None

			if tree_ls_info is None:
				raise NoSuchNode(path, rev)

			(self.perm,k,self.sha,fn) = tree_ls_info

			rev=self.git.last_change(rev, p)

			if k=='tree':
				pass
			elif k=='blob':
				kind = Node.FILE
			else:
				self.log.debug("kind is "+k)

		self.created_path = path
		self.created_rev = rev

		if branch:
			path = branch + "/" + path

		Node.__init__(self, path, rev, kind)

	def get_content(self):
		if self.isfile:
			return self.git.get_file(self.sha)

		return None

	def get_properties(self):
		if self.perm:
			return {'mode': self.perm }
		return {}

	def get_entries(self):
		if self.isfile:
			return
		if not self.isdir:
			return

		p = self.created_path.strip('/')
		if p != '': p = p + '/'
		for e in self.git.tree_ls(self.rev, p):
			yield GitNode(self.git, self.log, e[3], self.branch, self.rev, e)

	def get_content_type(self):
		if self.isdir:
			return None
		return ''

	def get_content_length(self):
		if self.isfile:
			if not self.data_len:
				self.data_len = self.git.get_obj_size(self.sha)
			return self.data_len
		return None

	def get_history(self, limit=None):
		p = self.created_path.strip('/')
		for rev in self.git.history(self.rev, p, limit):
			yield (self.path, rev, Changeset.EDIT)

	def get_last_modified(self):
		return None

class GitChangeset(Changeset):
	def __init__(self, git, sha):
		self.git = git
		try:
			(msg,props) = git.read_commit(sha)
		except PyGIT.GitErrorSha:
			raise NoSuchChangeset(sha)
		self.props = props

		committer = props['committer'][0]
		(user,time,tz) = committer.rsplit(None, 2)

		Changeset.__init__(self, sha, msg, user, float(time))

	def get_properties(self):
		for k in self.props:
			v = self.props[k]
			if k in ['committer', 'author']:
				yield("git_"+k, ", ".join(v), False, 'author')
			if k in ['parent']:
				yield("git_"+k, ", ".join(("[%s]" % c) for c in v), True, 'changeset')

	def get_changes(self):
		prev = self.props.has_key('parent') and self.props['parent'][0] or None
		for chg in self.git.diff_tree(prev, self.rev):
			#print chg
			(mode1,mode2,obj1,obj2,action,path) = chg

			kind = Node.FILE
			if mode2.startswith('04') or mode1.startswith('04'):
				kind = Node.DIRECTORY

			if action == 'A':
				change = Changeset.ADD
			elif action == 'M':
				change = Changeset.EDIT
			elif action == 'D':
				change = Changeset.DELETE
			else:
				raise "OhOh"

			yield (path, kind, change, path, prev)
