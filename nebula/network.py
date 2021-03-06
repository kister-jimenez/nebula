import logging
import subprocess
import time
import random
import string
import os

import fabric
from fabric import Connection
from nebula.common import utils

log = logging.getLogger(__name__)


class network(utils):
    def __init__(
        self,
        dutip=None,
        dutusername=None,
        dutpassword=None,
        dhcp=None,
        nic=None,
        nicip=None,
        yamlfilename=None,
        board_name=None,
    ):
        props = ["dutip", "dutusername", "dutpassword", "dhcp", "nic", "nicip"]
        for prop in props:
            setattr(self, prop, None)
        self.update_defaults_from_yaml(
            yamlfilename, __class__.__name__, board_name=board_name
        )
        props = ["dutip", "dutusername", "dutpassword", "dhcp", "nic", "nicip"]
        for prop in props:
            if eval(prop) != None:
                setattr(self, prop, eval(prop))
        # Set sane defaults if everything still blank
        if not self.dutusername:
            self.dutusername = "root"
        if not self.dutpassword:
            self.dutpassword = "analog"
        if not self.dhcp:
            self.dhcp = False
        self.ssh_timeout = 30

    def ping_board(self, tries=10):
        """ Ping board and check if any received

            return: True non-zero received, False zero received
        """
        log.info("Checking for board through ping")
        for p in range(tries):
            try:
                ping = subprocess.Popen(
                    ["ping", "-c", "4", self.dutip],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                out, error = ping.communicate()
                break
            except:
                log.error("Ping creation failed")
                if p>=(tries-1):
                    raise Exception("Ping creation sfailed")
                time.sleep(3)
            if "0 received" not in str(out):
                return False
        return True

    def check_ssh(self):
        """ SSH to board board and check if its possible to run any command

            return: True working ssh, False non-working ssh
        """
        retries = 3
        for t in range(retries):
            try:
                log.info("Checking for board through SSH")
                result = fabric.Connection(
                    self.dutusername + "@" + self.dutip,
                    connect_kwargs={"password": self.dutpassword},
                ).run("uname -a", hide=True, timeout=self.ssh_timeout)
                break
            except Exception as ex:
                log.warning("Exception raised: "+str(ex))
                time.sleep(3)
                if t>=(retries-1):
                    raise Exception("SSH Failed")
        return result.failed

    def check_board_booted(self):
        """ Check if board has network activity with ping, then check SSH working
            This function raises exceptions on failures
        """
        if self.ping_board():
            raise Exception("Board not booted")
        else:
            logging.info("PING PASSED")

        if self.check_ssh():
            raise Exception("SSH failing")
        else:
            logging.info("SSH PASSED")

    def reboot_board(self, bypass_sleep=False):
        """ Reboot board over SSH, otherwise raise exception
        """
        log.info("Rebooting board over SSH")
        # Try to reboot board with SSH if possible
        retries = 3
        for t in range(retries):
            try:
                result = fabric.Connection(
                    self.dutusername + "@" + self.dutip,
                    connect_kwargs={"password": self.dutpassword},
                ).run("/sbin/reboot", hide=False)
                if result.ok:
                    print("Rebooting board with SSH")
                    if not bypass_sleep:
                        time.sleep(30)
                    break
                else:
                    # Use PDU
                    raise Exception("PDU reset not implemented yet")

            except Exception as ex:
                log.warning("Exception raised: "+str(ex))
                time.sleep(3)
                if t>=(retries-1):
                    raise Exception("Exception occurred during SSH Reboot", str(ex))
    
    def run_ssh_command(self, command, ignore_exceptions=False):
        retries = 3
        result=None
        for t in range(retries):
            log.info("ssh command:" + command +" to "+self.dutusername + "@" + self.dutip)
            try:
                result = fabric.Connection(
                    self.dutusername + "@" + self.dutip,
                    connect_kwargs={"password": self.dutpassword},
                ).run(command, hide=True, timeout=self.ssh_timeout)
                if result.failed:
                    raise Exception("Failed to run command:", command)
                break
            except Exception as ex:
                log.warning("Exception raised: "+str(ex))
                if not ignore_exceptions:
                    time.sleep(3)
                    if t>=(retries-1):
                        raise Exception("SSH Failed")
                
        return result

    def copy_file_to_remote(self, src, dest):
        retries = 3
        log.info("Copying file to remote: "+src)
        for t in range(retries):
            try:
                Connection(
                    self.dutusername + "@" + self.dutip,
                    connect_kwargs={"password": self.dutpassword},
                ).put(src, remote=dest)
            except Exception as ex:
                log.warning("Exception raised: "+str(ex))
                time.sleep(3)
                if t>=(retries-1):
                    raise Exception("SSH Failed")

    def update_boot_partition(
        self, bootbinpath=None, uimagepath=None, devtreepath=None
    ):
        """ update_boot_partition:
                Update boot files on existing card which from remote files
        """
        log.info("Updating boot files over SSH")
        try:
            self.run_ssh_command("ls /tmp/sdcard")
            dir_exists = True
        except:
            log.info("Existing /tmp/sdcard directory not found. Will need to create it")
            dir_exists = False
        if dir_exists:
            try:
                log.info("Trying to unmounting directory")
                self.run_ssh_command("umount /tmp/sdcard")
            except:
                log.info("Unmount failed... Likely not mounted")
                pass
        else:
            self.run_ssh_command("mkdir /tmp/sdcard")
        self.run_ssh_command("mount /dev/mmcblk0p1 /tmp/sdcard")
        if bootbinpath:
            self.copy_file_to_remote(bootbinpath, "/tmp/sdcard/")
        if uimagepath:
            self.copy_file_to_remote(uimagepath, "/tmp/sdcard/")
        if devtreepath:
            self.copy_file_to_remote(devtreepath, "/tmp/sdcard/")
        self.run_ssh_command("sudo reboot",ignore_exceptions=True)

    def update_boot_partition_existing_files(self, subfolder=None):
        """ update_boot_partition_existing_files:
                Update boot files on existing card which contains reference
                files in the BOOT partition

                You must specify the subfolder with the BOOT partition to use.
                For example: zynq-zc706-adv7511-fmcdaq2
        """
        log.info("Updating boot files over SSH from SD card itself")
        if not subfolder:
            raise Exception("Must provide a subfolder")
        self.run_ssh_command("mkdir /tmp/sdcard")
        self.run_ssh_command("mount /dev/mmcblk0p1 /tmp/sdcard")
        self.run_ssh_command("cp /tmp/sdcard/" + subfolder + "/BOOT.BIN /tmp/sdcard/")
        if "zynqmp" in subfolder:
            self.run_ssh_command("cp /tmp/sdcard/zynqmp-common/Image /tmp/sdcard/")
            self.run_ssh_command(
                "cp /tmp/sdcard/" + subfolder + "/system.dtb /tmp/sdcard/"
            )
        else:
            self.run_ssh_command("cp /tmp/sdcard/zynq-common/uImage /tmp/sdcard/")
            self.run_ssh_command(
                "cp /tmp/sdcard/" + subfolder + "/devicetree.dtb /tmp/sdcard/"
            )
        self.run_ssh_command("sudo reboot")

    def _dl_file(self, filename):
        fabric.Connection(
            self.dutusername + "@" + self.dutip,
            connect_kwargs={"password": self.dutpassword},
        ).get(filename)

    def check_dmesg(self, error_on_warnings=False):
        """ check_dmesg:
            Download and parse remote board's dmesg log

            return:
                dmesg_log string of dmesg log
                status: 0 if no errors found, 1 otherwise
        """
        tmp_filename_root = "".join(
            random.choice(string.ascii_lowercase) for i in range(16)
        )
        tmp_filename = "/tmp/" + tmp_filename_root
        tmp_filename_err = "/tmp/" + tmp_filename_root + "_err"
        tmp_filename_war = "/tmp/" + tmp_filename_root + "_warn"

        self.run_ssh_command("dmesg > " + tmp_filename)
        self.run_ssh_command("dmesg -l warn > " + tmp_filename_war)
        self.run_ssh_command("dmesg -l err > " + tmp_filename_err)
        self._dl_file(tmp_filename)
        self._dl_file(tmp_filename_war)
        self._dl_file(tmp_filename_err)
        os.rename(tmp_filename_root, "dmesg.log")
        os.rename(tmp_filename_root + "_warn", "dmesg_warn.log")
        os.rename(tmp_filename_root + "_err", "dmesg_err.log")
        logging.info("dmesg logs collected")

        # Process
        with open("dmesg.log", "r") as f:
            all_log = f.readlines()
        with open("dmesg_warn.log", "r") as f:
            warn_log = f.readlines()
        with open("dmesg_err.log", "r") as f:
            error_log = f.readlines()

        if len(error_log) > 0:
            logging.info("Errors found in dmesg logs")

        logs = {"log": all_log, "warn": warn_log, "error": error_log}
        return len(error_log) > 0, logs
