#
# Copyright (C) 2013  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.  You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.  Any Red Hat trademarks that are incorporated in the
# source code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission of
# Red Hat, Inc.
#
# Red Hat Author(s): Vratislav Podzimek <vpodzime@redhat.com>
#

"""
Module with various classes for handling pre-installation rules.

"""

import optparse
import shlex

from org_fedora_oscap import common
from org_fedora_oscap.common import OSCAPaddonError, RuleMessage

# everything else should be private
__all__ = ["RuleData"]

# TODO: enable translations
_ = lambda x: x

# TODO: use set instead of list for mount options?
def parse_csv(option, opt_str, value, parser):
    for item in value.split(","):
        if item:
            parser.values.ensure_value(option.dest, []).append(item)

PART_RULE_PARSER = optparse.OptionParser()
PART_RULE_PARSER.add_option("--mountoptions", dest="mount_options",
                            action="callback", callback=parse_csv, nargs=1,
                            type="string")

PASSWD_RULE_PARSER = optparse.OptionParser()
PASSWD_RULE_PARSER.add_option("--minlen", dest="minlen", action="store",
                              default=0, type="int")

PACKAGE_RULE_PARSER = optparse.OptionParser()
PACKAGE_RULE_PARSER.add_option("--add", dest="add_pkgs", action="append",
                               type="string")
PACKAGE_RULE_PARSER.add_option("--remove", dest="remove_pkgs", action="append",
                               type="string")

BOOTLOADER_RULE_PARSER = optparse.OptionParser()
BOOTLOADER_RULE_PARSER.add_option("--passwd", dest="passwd", action="store_true",
                                  default=False)

class RuleHandler(object):
    """Base class for the rule handlers."""

    def eval_rules(self, ksdata, storage, report_only=False):
        """
        Method that should check the current state (as defined by the ksdata and
        storage parameters) against the rules the instance of RuleHandler
        holds. Depending on the value of report_only it should fix the state
        with changes that can be done automatically or not and return the list
        of warnings and errors for fixes that need to be done manually together
        with info messages about the automatic changes. One should make sure
        this method is called with report_only set to False at least once so
        that the automatic fixes are done.

        :param ksdata: data representing the values set by user
        :type ksdata: pykickstart.base.BaseHandler
        :param storage: object storing storage-related information
                        (disks, partitioning, bootloader, etc.)
        :type storage: blivet.Blivet
        :param report_only: whether to do fixing or just report information
        :type report_only: bool
        :return: errors and warnings for fixes that need to be done manually and
                 info messages about the automatic changes
        :rtype: list of common.RuleMessage objects

        """

        return []

class UknownRuleError(OSCAPaddonError):
    """Exception class for cases when an uknown rule is to be processed."""

    pass

class RuleData(RuleHandler):
    """Class holding data parsed from the applied rules."""

    def __init__(self):
        """Constructor initializing attributes."""

        self._part_rules = PartRules()
        self._passwd_rules = PasswdRules()
        self._package_rules = PackageRules()
        self._bootloader_rules = BootloaderRules()

    def __str__(self):
        """Standard method useful for debugging and testing."""

        ret = ""

        part_strs = str(self._part_rules)
        if part_strs:
            ret += part_strs

        passwd_str = str(self._passwd_rules)
        if passwd_str:
            ret += "\n" + passwd_str

        packages_str = str(self._package_rules)
        if packages_str:
            ret += "\n" + packages_str

        return ret

    def new_rule(self, rule):
        """
        Method that handles a single rule line (e.g. "part /tmp").

        :param rule: a single rule line
        :type rule: str

        """

        actions = { "part" : self._new_part_rule,
                    "passwd" : self._new_passwd_rule,
                    "package": self._new_package_rule,
                    "bootloader": self._new_bootloader_rule,
                    }

        rule = rule.strip()
        if not rule:
            return

        first_word = rule.split(None, 1)[0]
        try:
            actions[first_word](rule)
        except KeyError:
            # should never happen
            # TODO: only log error instead?
            raise UknownRuleError("Unknown rule: '%s'" % first_word)

    def eval_rules(self, ksdata, storage, report_only=False):
        """:see: RuleHandler.eval_rules"""

        messages = []

        # evaluate all subgroups of rules
        for rule_handler in (self._part_rules, self._passwd_rules,
                             self._package_rules, self._bootloader_rules,):
            messages += rule_handler.eval_rules(ksdata, storage, report_only)

        return messages

    def _new_part_rule(self, rule):
        args = shlex.split(rule)
        (opts, args) = PART_RULE_PARSER.parse_args(args)

        # args contain both "part" and mount point (e.g. "/tmp")
        mount_point = args[1]

        self._part_rules.ensure_mount_point(mount_point)

        if opts.mount_options:
            part_data = self._part_rules[mount_point]
            part_data.add_mount_options(opts.mount_options)

    def _new_passwd_rule(self, rule):
        args = shlex.split(rule)
        (opts, args) = PASSWD_RULE_PARSER.parse_args(args)

        self._passwd_rules.update_minlen(opts.minlen)

    def _new_package_rule(self, rule):
        args = shlex.split(rule)
        (opts, args) = PACKAGE_RULE_PARSER.parse_args(args)

        self._package_rules.add_packages(opts.add_pkgs)
        self._package_rules.remove_packages(opts.remove_pkgs)

    def _new_bootloader_rule(self, rule):
        args = shlex.split(rule)
        (opts, args) = BOOTLOADER_RULE_PARSER.parse_args(args)

        if opts.passwd:
            self._bootloader_rules.require_password()

class PartRules(RuleHandler):
    """Simple class holding data from the rules affecting partitioning."""

    def __init__(self):
        """Constructor initializing attributes."""

        self._rules = dict()

    def __str__(self):
        """Standard method useful for debugging and testing."""

        return "\n".join(str(rule) for rule in self._rules.itervalues())

    def __getitem__(self, key):
        """Method to support dictionary-like syntax."""

        return self._rules[key]

    def __setitem__(self, key, value):
        """Method to support dictionary-like syntax."""

        self._rules[key] = value

    def __delitem__(self, key):
        """One of the methods needed to implement a container."""

        self._rules.__delitem__(key)

    def __len__(self):
        """One of the methods needed to implement a container."""

        return self._rules.__len__()

    def __contains__(self, key):
        """Method needed for the 'in' operator to work."""

        return key in self._rules

    def ensure_mount_point(self, mount_point):
        if mount_point not in self._rules:
            self._rules[mount_point] = PartRule(mount_point)

    def eval_rules(self, ksdata, storage, report_only=False):
        """:see: RuleHandler.eval_rules"""

        messages = []
        for part_rule in self._rules.itervalues():
            messages += part_rule.eval_rules(ksdata, storage, report_only)

        return messages

class PartRule(RuleHandler):
    """Simple class holding rule data for a single partition/mount point."""

    def __init__(self, mount_point):
        """
        Constructor initializing attributes.

        :param mount_point: the mount point the object holds data for
        :type mount_point: str

        """

        self._mount_point = mount_point
        self._mount_options = []

    def __str__(self):
        """Standard method useful for debugging and testing."""

        ret = "part %s" % self._mount_point
        if self._mount_options:
            ret +=  " --mountoptions=%s" % ",".join(self._mount_options)

        return ret

    def add_mount_options(self, mount_options):
        """
        Add  new mount options (do not add duplicates).

        :param mount_options: list of mount options to be added
        :type mount_options: list of strings

        """

        self._mount_options.extend(opt for opt in mount_options
                                   if opt not in self._mount_options)

    def eval_rules(self, ksdata, storage, report_only=False):
        """:see: RuleHandler.eval_rules"""

        messages = []
        if self._mount_point not in storage.mountpoints:
            msg = _("%s must be on a separate partition or logical "
                    "volume" % self._mount_point)
            messages.append(RuleMessage(common.MESSAGE_TYPE_FATAL, msg))

            # mount point doesn't exist, nothing more can be found here
            return messages

        # mount point to be created during installation
        target_mount_point = storage.mountpoints[self._mount_point]

        # new options that should be added
        new_opts = (opt for opt in self._mount_options
                    if opt not in target_mount_point.format.options.split(","))

        new_opts_str = ""
        for opt in new_opts:
            new_opts_str += ",%s" % opt
            msg = _("mount option '%s' added for the mount point %s" % (opt,
                                                             self._mount_point))
            messages.append(RuleMessage(common.MESSAGE_TYPE_INFO, msg))

        # add new options to the target mount point
        if not report_only:
            target_mount_point.format.options += new_opts_str

        return messages

class PasswdRules(RuleHandler):
    """Simple class holding data from the rules affecting passwords."""

    def __init__(self):
        """Constructor initializing attributes."""

        self._minlen = 0

    def __str__(self):
        """Standard method useful for debugging and testing."""

        if self._minlen > 0:
            return "passwd --minlen=%d" % self._minlen
        else:
            return ""

    def update_minlen(self, minlen):
        """Update password minimal length requirements."""

        if minlen > self._minlen:
            self._minlen = minlen

    def eval_rules(self, *args):
        """:see: RuleHandler.eval_rules"""

        if self._minlen > 0:
            # password length enforcement is not suported in the Anaconda yet
            msg = _("make sure to create password with minimal length of %d "
                    "characters" % self._minlen)
            return [RuleMessage(common.MESSAGE_TYPE_WARNING, msg)]
        else:
            return []

class PackageRules(RuleHandler):
    """Simple class holding data from the rules affecting installed packages."""

    def __init__(self):
        """Constructor setting the initial value of attributes."""

        self._add_pkgs = set()
        self._remove_pkgs = set()

    def add_packages(self, packages):
        """
        New packages that should be added.

        :param packages: packages to be added
        :type packages: iterable

        """

        if packages:
            self._add_pkgs.update(packages)

    def remove_packages(self, packages):
        """
        New packages that should be removed.

        :param packages: packages to be removed
        :type packages: iterable

        """

        if packages:
            self._remove_pkgs.update(packages)

    def __str__(self):
        """Standard method useful for debugging and testing."""

        ret = "packages"
        adds = " ".join("--add=%s" % package for package in self._add_pkgs)
        if adds:
            ret += " " + adds

        rems = " ".join("--remove=%s" % package
                        for package in self._remove_pkgs)
        if rems:
            ret += " " + rems

        return ret

    def eval_rules(self, ksdata, storage, report_only=False):
        """:see: RuleHandler.eval_rules"""

        messages = []
        for pkg in self._add_pkgs:
            # add the package unless already added
            if not report_only and pkg not in ksdata.packages.packageList:
                ksdata.packages.packageList.append(pkg)

            msg = _("package '%s' has been added to the list of to be installed "
                    "packages" % pkg)
            messages.append(RuleMessage(common.MESSAGE_TYPE_INFO, msg))

        for pkg in self._remove_pkgs:
            # exclude the package unless already excluded
            if not report_only and pkg not in ksdata.packages.excludedList:
                ksdata.packages.excludedList.append(pkg)

            msg = _("package '%s' has been added to the list of excluded "
                    "packages" % pkg)
            messages.append(RuleMessage(common.MESSAGE_TYPE_INFO, msg))

        return messages

class BootloaderRules(RuleHandler):
    """Simple class holding data from the rules affecting bootloader."""

    def __init__(self):
        """Constructor setting the initial value of attributes."""

        self._require_password = False

    def require_password(self):
        """Requests the bootloader password should be required."""

        self._require_password = True

    def __str__(self):
        """Standard method useful for debugging and testing."""

        ret = "bootloader"

        if self._require_password:
            ret += " --passwd"

        return ret

    # TODO: check if the bootloader password is set in eval_rules and return
    #       warning if not (cannot return error, since Anaconda doesn't support
    #       bootloader password setup in the GUI)
