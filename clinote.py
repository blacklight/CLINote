#!/usr/bin/python

###################
# CLINote - A command-line tool for synchronizing your ~/evernote local directory with your Evernote notebooks
#
# Usage:
#   * ##### Get an API key for Evernote here: http://dev.evernote.com/support/api_key.php #####
#   * Paste your API key in the "authToken" variable in this script
#   * Start this script. A folder named "~/evernote" will be created on your filesystem.
#     It will be populated with the notebooks and the notes on your Evernote account.
#     All the HTML notes will be converted to plain text
#   * Any directory you create under "~/evernote", will be considered as a new notebook, and synchronized with your account
#   * Any change you perform on the existing notes/notebooks, will be commited on your account as well
#   * Any note created under a notebook directory, will be committed on your account
#
# Dependencies:
#
# Evernote Python SDK (https://github.com/evernote/evernote-sdk-python)
# pyinotify (apt-get install python-pyinotify)
# Python BeautifulSoup (apt-get install python-beautifulsoup)
#
# by Fabio "BlackLight" Manganiello <blacklight86@gmail.com>
# Released under Apache License 2.0 and later
#
###################

##########################
# Your authToken goes here
# Get your API key here: http://dev.evernote.com/support/api_key.php
authToken = "Your API token goes here"
##########################

import os
import re
import string
import logging
import codecs
import hashlib
import pyinotify
import binascii
import thrift.protocol.TBinaryProtocol as TBinaryProtocol
import thrift.transport.THttpClient as THttpClient
import evernote.edam.userstore.UserStore as UserStore
import evernote.edam.userstore.constants as UserStoreConstants
import evernote.edam.notestore.NoteStore as NoteStore
import evernote.edam.type.ttypes as Types
from time import time
from subprocess import call
from threading import Thread
from BeautifulSoup import BeautifulSoup

class FilesystemEvent(pyinotify.ProcessEvent):
	def __init__(self, evernote, path = os.environ['HOME'] + '/evernote'):
		pyinotify.ProcessEvent.__init__(self)
		self.path = path
		self.evernote = evernote

	def __is_excluded_file__(self, fname):
		return True if re.search('\.swpx?$', fname) or re.search('/\.config/', fname) or re.search('/src/', fname) else False

	def process_IN_CREATE(self, event):
		logging.debug("File created: '%s'" % (event.path + "/" + event.name))
		if self.__is_excluded_file__(event.path + "/" + event.name):
			return

		logging.debug("'%s' is not an excluded pattern" % (event.path + "/" + event.name))
		if os.path.isdir(event.name) and self.evernote.getNotebookByName(event.name) is None:
			notebook = self.evernote.createNotebook(event.name)
			if notebook:
				logging.info("Notebook '%s' successfully created" % event.name)
				try:
					call(['notify-send', 'Notebook "%s" successfully created' % (event.name)])
				except:
					pass
			else:
				logging.error("Could not create the notebook '%s'" % event.name)
			return
		else:
			logging.debug("'%s' is not a new notebook" % (event.path + "/" + event.name))

		notebook, note = self.evernote.getNoteByPath(event.path + "/" + event.name)
		if notebook is None or (notebook is not None and note is not None):
			return

		try:
			content = open(event.path + "/" + event.name, 'r').read()
		except IOError:
			return

		note = self.evernote.createNote(title=event.name, content=content, notebook=notebook)
		if note:
			try:
				call(['notify-send', 'Note "%s/%s" successfully created' % (notebook.name, note.title)])
			except:
				pass

			logging.info("Note '%s/%s' successfully created" % (notebook.name, note.title))
		else:
			logging.error("Could not create the note '%s/%s'" % (notebook.name, note.title))

	def process_IN_DELETE(self, event):
		logging.debug("File deleted: '%s'" % (event.path + "/" + event.name))
		if self.__is_excluded_file__(event.path + "/" + event.name):
			return

		logging.debug("'%s' is not an excluded pattern" % (event.path + "/" + event.name))
		notebook = self.evernote.getNotebookByName(event.name)
		if notebook is not None and os.path.isdir(event.name):
			self.evernote.expungeNotebook(notebook)
			logging.info("Notebook '%s' successfully deleted" % event.name)
			try:
				call(['notify-send', 'Notebook "%s" successfully deleted' % (event.name)])
			except:
				pass
			return

		notebook, note = self.evernote.getNoteByPath(event.path + "/" + event.name)
		if notebook is None or note is None:
			return

		self.evernote.deleteNote(note)
		logging.info("Note '%s/%s' deleted" % (notebook.name, note.title))
		try:
			call(['notify-send', 'Note "%s/%s" successfully deleted' % (notebook.name, note.title)])
		except:
			pass

	def process_IN_MODIFY(self, event):
		if self.__is_excluded_file__(event.path + "/" + event.name):
			return

		notebook, note = self.evernote.getNoteByPath(event.path + "/" + event.name)
		if notebook is None or note is None:
			return

		try:
			note.content = open(event.path + "/" + event.name, 'r').read()
		except IOError:
			return

		note = self.evernote.updateNote(note)
		if note:
			try:
				call(['notify-send', 'Note "%s/%s" successfully updated' % (notebook.name, note.title)])
			except:
				pass

			logging.info("Note '%s/%s' successfully updated" % (notebook.name, note.title))
		else:
			logging.error("Could not update the note '%s/%s'" % (notebook.name, note.title))


class Evernote:
	def __init__(self, evernoteHost, authToken, basepath=os.environ["HOME"] + "/evernote"):
		self.authToken = authToken
		self.evernoteHost = evernoteHost
		self.basepath = basepath
		self.notebooks = None
		self.notes = None
		self.__mkdir__(basepath)
		self.__mkdir__(basepath + "/.config")
		self.__mkdir__(basepath + "/.config/cache")
		logging.basicConfig(filename=os.environ['HOME'] + "/evernote/.config/evernote.log",
			format='%(asctime)s | %(levelname)7s | %(message)s',
			level=logging.DEBUG)
		logging.info("======================")
		logging.info("CLINote Daemon started")
		logging.info("======================")

		inotifyMask = pyinotify.IN_CREATE | pyinotify.IN_DELETE | pyinotify.IN_MODIFY
		wm = pyinotify.WatchManager()
		self.notifier = pyinotify.ThreadedNotifier(wm, FilesystemEvent(self, basepath))
		excl = pyinotify.ExcludeFilter(['.*.swp', '.*.swpx', '/\.config/', '/src/'])
		wm.add_watch(basepath, inotifyMask, rec=True, auto_add=True, exclude_filter=excl)

		userStoreUri = "https://" + evernoteHost + "/edam/user"
		self.userStoreHttpClient = THttpClient.THttpClient(userStoreUri)
		self.userStoreProtocol = TBinaryProtocol.TBinaryProtocol(self.userStoreHttpClient)
		self.userStore = UserStore.Client(self.userStoreProtocol)

		versionOK = self.userStore.checkVersion("Evernote EDAMTest (Python)",
			UserStoreConstants.EDAM_VERSION_MAJOR,
			UserStoreConstants.EDAM_VERSION_MINOR)

		if not versionOK:
			raise Exception("Evernote API version mismatch")

		self.noteStoreUrl = self.userStore.getNoteStoreUrl(authToken)
		self.noteStoreHttpClient = THttpClient.THttpClient(self.noteStoreUrl)
		self.noteStoreProtocol = TBinaryProtocol.TBinaryProtocol(self.noteStoreHttpClient)
		self.noteStore = NoteStore.Client(self.noteStoreProtocol)
		logging.info("Evernote log in OK")

	def __mkdir__(self, path):
		try:
			os.makedirs(path)
		except OSError as err:
			if err.errno == os.errno.EEXIST and os.path.isdir(path):
				pass
			else:
			 	raise

	def __getTagName__(self, htmlString):
		m = re.match('^\s*<([^/>]+)/?>', htmlString)
		return m.group(1) if m else None

	def __soup2text__(self, soup):
		self.styleTags = ['b', 'i', 'strong', 'em', 'span', 'ul']
		self.listTags = ['li', 'ol']
		v = soup.string
		if v == None:
			c=soup.contents
			resulttext = ''
			for t in c:
				subtext = self.__soup2text__(t)
				tagName = self.__getTagName__(str(t))
				resultText = ""
				
				if tagName in self.listTags:
					resultText += "\t*  "
				resulttext += subtext.strip()
				if not tagName in self.styleTags:
					resulttext += '\n'
			return unicode(resulttext).strip()
		else:
			return unicode(v).strip()

	def normalizeNoteName(self, notename):
		return notename[:100]

	def initNotebooks(self):
		if self.notebooks is None:
			self.notebooks = self.listNotebooks()
			logging.info("Notebooks initialized")

		syncNotes = False
		if self.notes is None:
			self.notes = {}
			syncNotes = True

		for notebook in self.notebooks:
			notebookPath = self.basepath + "/" + notebook.name
			notebookCachePath = self.basepath + "/.config/cache/" + notebook.name
			self.__mkdir__(notebookPath)
			self.__mkdir__(notebookPath + "/src")
			self.__mkdir__(notebookCachePath)
			logging.info("Initializing notebook '%s'" % (notebookPath))

			if syncNotes:
				self.notes[notebook.name] = self.listNotesByNotebook(notebook.guid)

				for n in self.notes[notebook.name]:
					noteFname = self.normalizeNoteName(n.title)
					updateNote = False
					if not os.path.isfile(notebookCachePath + "/" + noteFname + ".mtime"):
						updateNote = True

					localLastUpdTime = 0
					try:
						f = open(notebookCachePath + "/" + noteFname + ".mtime", "r")
						localLastUpdTime = long(f.readlines()[0])
						f.close()
					except IOError:
						pass

					noteLastUpdTime = long(str(n.updated)[:len(str(n.updated))-3])
					if noteLastUpdTime >= localLastUpdTime:
						updateNote = True

					if updateNote:
						logging.info("Initializing note '%s'" % (notebookPath + "/" + noteFname))
						n.content = self.noteStore.getNoteContent(self.authToken, n.guid)
						f = open(notebookPath + "/src/" + noteFname, 'w')
						f.write(n.content)
						f.close()

						n.content = string.join(n.content.splitlines()[2:])
						soup = BeautifulSoup(n.content)
						text = self.__soup2text__(soup).strip() + "\n"
						f = codecs.open(notebookPath + "/" + noteFname, 'w', 'utf-8')
						f.write(text)
						f.close()

						f = open(notebookCachePath + "/" + noteFname + ".mtime", "w")
						f.write(str(int(time())) + "\n")
						f.close()
					else:
						logging.info("Note '%s' is already up-to-date, skipped" % (notebookPath + '/' + noteFname))

	def startNotifier(self):
		self.notifier.start()

	def listNotebooks(self):
		return self.noteStore.listNotebooks(self.authToken)

	def listNotesByNotebook(self, notebookGUID):
		filter = NoteStore.NoteFilter()
		filter.notebookGuid = notebookGUID
		noteList = self.noteStore.findNotes(self.authToken, filter, 0, 99999)
		return noteList.notes

	def getNoteContent(self, guid):
		return self.noteStore.getNoteContent(authToken, guid)

	def getNotebookByName(self, name):
		for notebook in self.notebooks:
			if notebook.name == name:
				return notebook
		return None

	def getNotebookByGUID(self, guid):
		for notebook in self.notebooks:
			if notebook.guid == guid:
				return notebook
		return None

	def getNoteByPath(self, path):
		notebook = self.getNotebookByName(re.sub('.*/([^/]+)\s*$', '\g<1>', os.path.dirname(path)))
		notename = re.sub('.*/([^/]+)\s*$', '\g<1>', path)
		if notebook is None:
			return [None, None]

		for note in self.notes[notebook.name]:
			if note.title[:len(notename)] == notename:
				return [notebook, note]

		return [notebook, None]

	def getNoteIndexInNotebook(self, note, notebook):
		if not notebook.name in self.notes:
			return -1
		for i in range(0, len(self.notes[notebook.name])):
			n = self.notes[notebook.name][i]
			if n.guid == note.guid:
				return i
		return -1

	def createNotebook(self, name):
		notebook = Types.Notebook()
		notebook.name = name
		notebook = self.noteStore.createNotebook(self.authToken, notebook)
		if notebook is not None:
			self.notebooks.append(notebook)
			self.notes[notebook.name] = []
			self.__mkdir__(self.basepath + "/" + notebook.name + "/src")
		return notebook

	def expungeNotebook(self, notebook):
		if notebook.name in self.notes:
			del self.notes[notebook.name]

		for i in range(0, len(self.notebooks)):
			if self.notebooks[i].guid == notebook.guid:
				del self.notebooks[i]
				break

		self.noteStore.expungeNotebook(self.authToken, notebook.guid)

	def createNote(self, title, content, notebook):
		note = Types.Note()
		note.title = self.normalizeNoteName(title)
		note.notebookGuid = notebook.guid
		note.content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE en-note SYSTEM "http://xml.evernote.com/pub/enml2.dtd">
<en-note><pre>%s</pre></en-note>
""" % (self.__xmlParse__(content))

		note = self.noteStore.createNote(self.authToken, note)
		if note:
			self.notes[notebook.name].append(note)
		return note

	def updateNote(self, note):
		note.content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE en-note SYSTEM "http://xml.evernote.com/pub/enml2.dtd">
<en-note><pre>%s</pre></en-note>
""" % (self.__xmlParse__(note.content))

		return self.noteStore.updateNote(self.authToken, note)

	def deleteNote(self, note):
		notebook = self.getNotebookByGUID(note.notebookGuid)
		if notebook:
			idx = self.getNoteIndexInNotebook(note, notebook)
			if idx > -1:
				del self.notes[notebook.name][idx]

		self.noteStore.deleteNote(self.authToken, note.guid)

	def __xmlParse__(self, content):
		# return content.replace("\n", "<br/>\n")
		return content.replace("<", "&lt;").replace(">", "&gt;")

evernote = Evernote('www.evernote.com', authToken)
evernote.initNotebooks()
logging.info("Evernote synchronization completed")
evernote.startNotifier()

