"""
Root tests - contain tests which need to be run as root.

Some of the quoting here may not work with csh (works on bash).
Requires the usage of sudo to determine the normal user name and ID,
or the explicit definition of RDIFF_TEST_UID and RDIFF_TEST_USER.
"""

import os
import unittest

import commontest as comtst

from rdiff_backup import rpath
from rdiffbackup.singletons import consts, generics, specifics

TEST_BASE_DIR = comtst.get_test_base_dir(__file__)

assert os.getuid() == 0, "Run this test as root!"

# we need a normal user for our test, we use environment variables to use
# the right one, either through SUDO_* variables set by sudo, or set
# explicitly by the tester.
userid = int(os.getenv("RDIFF_TEST_UID", os.getenv("SUDO_UID")))
user = os.getenv("RDIFF_TEST_USER", os.getenv("SUDO_USER"))
assert userid, "Unable to assess ID of non-root user to be used for tests"
assert user, "Unable to assess name of non-root user to be used for tests"


class BaseRootTest(unittest.TestCase):
    out_dir = os.path.join(TEST_BASE_DIR, b"output")
    restore_dir = os.path.join(TEST_BASE_DIR, b"restore")

    def _run_cmd(self, cmd, expect_rc=consts.RET_CODE_OK):
        print("Running: ", cmd)
        rc = comtst.os_system(cmd)
        self.assertEqual(
            rc, expect_rc, "Command '{cmd}' failed with rc={rc}".format(cmd=cmd, rc=rc)
        )


class RootTest(BaseRootTest):
    dirlist1 = [
        os.path.join(comtst.old_test_dir, b"root"),
        os.path.join(comtst.old_test_dir, b"various_file_types"),
        os.path.join(comtst.old_test_dir, b"increment4"),
    ]
    dirlist2 = [
        os.path.join(comtst.old_test_dir, b"increment4"),
        os.path.join(comtst.old_test_dir, b"root"),
        os.path.join(comtst.old_test_dir, b"increment1"),
    ]

    def testLocal1(self):
        comtst.backup_restore_series(
            1, 1, self.dirlist1, compare_ownership=1, test_base_dir=TEST_BASE_DIR
        )

    def testLocal2(self):
        comtst.backup_restore_series(
            1, 1, self.dirlist2, compare_ownership=1, test_base_dir=TEST_BASE_DIR
        )

    def testRemote(self):
        comtst.backup_restore_series(
            None, None, self.dirlist1, compare_ownership=1, test_base_dir=TEST_BASE_DIR
        )

    def test_ownership(self):
        """
        Test backing up and restoring directory with different uids

        This checks for a bug in 0.13.4 where uids and gids would not
        be restored correctly.

        Also test to make sure symlinks get the right ownership.
        (Earlier symlink ownership was not preserved.)
        """
        dirrp = rpath.RPath(
            specifics.local_connection, os.path.join(TEST_BASE_DIR, b"root_owner")
        )

        def make_dir():
            comtst.re_init_rpath_dir(dirrp)
            rp1 = dirrp.append("file1")
            rp2 = dirrp.append("file2")
            rp3 = dirrp.append("file3")
            rp4 = dirrp.append("file4")
            rp5 = dirrp.append("symlink")
            rp1.touch()
            rp2.touch()
            rp3.touch()
            rp4.touch()
            rp5.symlink(b"foobar")
            rp1.chown(2000, 2000)
            rp2.chown(2001, 2001)
            rp3.chown(2002, 2002)
            rp4.chown(2003, 2003)
            rp5.chown(2004, 2004)

        make_dir()
        dirlist = [
            os.path.join(TEST_BASE_DIR, b"root_owner"),
            os.path.join(comtst.old_test_dir, b"empty"),
            os.path.join(TEST_BASE_DIR, b"root_owner"),
        ]
        comtst.backup_restore_series(
            1, 1, dirlist, compare_ownership=1, test_base_dir=TEST_BASE_DIR
        )
        # this works only because we know that backup_restore_series creates
        # the backup in the 'output' sub-directory
        symrp = rpath.RPath(
            specifics.local_connection,
            os.path.join(TEST_BASE_DIR, b"output", b"symlink"),
        )
        self.assertTrue(symrp.issym())
        self.assertEqual(symrp.getuidgid(), (2004, 2004))

    def test_ownership_mapping(self):
        """Test --user-mapping-file and --group-mapping-file options"""

        def write_ownership_dir():
            """Write the directory testfiles/root_mapping"""
            rp = rpath.RPath(
                specifics.local_connection, os.path.join(TEST_BASE_DIR, b"root_mapping")
            )
            comtst.re_init_rpath_dir(rp)
            rp1 = rp.append("1")
            rp1.touch()
            rp2 = rp.append("2")
            rp2.touch()
            rp2.chown(userid, 1)  # use groupid 1, usually bin
            return rp

        def write_mapping_files(dir_rp):
            """Write user and group mapping files, return paths"""
            user_map_rp = dir_rp.append("user_map")
            group_map_rp = dir_rp.append("group_map")
            user_map_rp.write_string("root:%s\n%s:root" % (user, user))
            group_map_rp.write_string("0:1")
            return user_map_rp.path, group_map_rp.path

        def get_ownership(dir_rp):
            """Return pair (ids of dir_rp/1, ids of dir_rp2) of ids"""
            rp1, rp2 = list(map(dir_rp.append, ("1", "2")))
            self.assertTrue(rp1.isreg())
            self.assertTrue(rp2.isreg())
            return (rp1.getuidgid(), rp2.getuidgid())

        in_rp = write_ownership_dir()
        user_map, group_map = write_mapping_files(in_rp)
        out_rp = rpath.RPath(specifics.local_connection, self.out_dir)
        if out_rp.lstat():
            comtst.remove_dir(out_rp.path)

        self.assertEqual(get_ownership(in_rp), ((0, 0), (userid, 1)))

        comtst.rdiff_backup(
            1,
            0,
            in_rp.path,
            out_rp.path,
            extra_options=(
                b"backup",
                b"--user-mapping-file",
                user_map,
                b"--group-mapping-file",
                group_map,
            ),
        )
        self.assertEqual(get_ownership(out_rp), ((userid, 0), (0, 1)))

    def test_numerical_mapping(self):
        """Test --preserve-numerical-ids option

        This doesn't really test much, since we don't have a
        convenient system with different uname/ids.

        """

        def write_ownership_dir():
            """Write the directory testfiles/root_mapping"""
            rp = rpath.RPath(
                specifics.local_connection, os.path.join(TEST_BASE_DIR, b"root_mapping")
            )
            comtst.re_init_rpath_dir(rp)
            rp1 = rp.append("1")
            rp1.touch()
            rp2 = rp.append("2")
            rp2.touch()
            rp2.chown(userid, 1)  # use groupid 1, usually bin
            return rp

        def get_ownership(dir_rp):
            """Return pair (ids of dir_rp/1, ids of dir_rp2) of ids"""
            rp1, rp2 = list(map(dir_rp.append, ("1", "2")))
            self.assertTrue(rp1.isreg())
            self.assertTrue(rp2.isreg())
            return (rp1.getuidgid(), rp2.getuidgid())

        in_rp = write_ownership_dir()
        out_rp = rpath.RPath(specifics.local_connection, self.out_dir)
        if out_rp.lstat():
            comtst.remove_dir(out_rp.path)

        self.assertEqual(get_ownership(in_rp), ((0, 0), (userid, 1)))

        comtst.rdiff_backup(
            1,
            0,
            in_rp.path,
            out_rp.path,
            extra_options=(b"backup", b"--preserve-numerical-ids"),
        )
        self.assertEqual(get_ownership(out_rp), ((0, 0), (userid, 1)))


class HalfRoot(BaseRootTest):
    """Backing up files where origin is root and destination is non-root"""

    def make_dirs(self):
        """Make source directories, return rpaths

        These make a directory with a changing file that is not
        self-readable.  (Caused problems earlier.)

        """
        rp1 = rpath.RPath(
            specifics.local_connection, os.path.join(TEST_BASE_DIR, b"root_half1")
        )
        comtst.re_init_rpath_dir(rp1)
        rp1_1 = rp1.append("foo")
        rp1_1.write_string("hello")
        rp1_1.chmod(0)
        rp1_2 = rp1.append("to be deleted")
        rp1_2.write_string("aosetuhaosetnuhontu")
        rp1_2.chmod(0)
        rp1_3 = rp1.append("unreadable_dir")
        rp1_3.mkdir()
        rp1_3_1 = rp1_3.append("file_inside")
        rp1_3_1.write_string("blah")
        rp1_3_1.chmod(0)
        rp1_3_2 = rp1_3.append("subdir_inside")
        rp1_3_2.mkdir()
        rp1_3_2_1 = rp1_3_2.append("foo")
        rp1_3_2_1.write_string("saotnhu")
        rp1_3_2_1.chmod(0)
        rp1_3_2.chmod(0)
        rp1_3.chmod(0)

        rp2 = rpath.RPath(
            specifics.local_connection, os.path.join(TEST_BASE_DIR, b"root_half2")
        )
        comtst.re_init_rpath_dir(rp2)
        rp2_1 = rp2.append("foo")
        rp2_1.write_string("goodbye")
        rp2_1.chmod(0)
        rp2_3 = rp2.append("unreadable_dir")
        rp2_3.mkdir()
        rp2_3_1 = rp2_3.append("file_inside")
        rp2_3_1.write_string("new string")
        rp2_3_1.chmod(0)
        rp2_3_2 = rp2_3.append("subdir_inside")
        rp2_3_2.mkdir()
        rp2_3_2_1 = rp2_3_2.append("foo")
        rp2_3_2_1.write_string("asoetn;oet")
        rp2_3_2_1.chmod(0)
        rp2_3_2.chmod(0)
        rp2_3_3 = rp2_3.append("file2")
        rp2_3_3.touch()
        rp2_3.chmod(0)
        # The rp_2_4 below test for a perm error, also tested in
        # regressiontest.py testConfig1
        rp2_4 = rp2.append("test2")
        rp2_4.mkdir()
        rp2_4_1 = rp2_4.append("1-dir")
        rp2_4_1.mkdir()
        reg2_4_1_1 = rp2_4_1.append("reg")
        reg2_4_1_1.touch()
        reg2_4_1_1.chmod(0)
        rp2_4_1.chmod(0)
        reg2_4_2 = rp2_4.append("2-reg")
        reg2_4_2.touch()
        reg2_4_2.chmod(0)
        rp2_4.chmod(0)

        return rp1, rp2

    def cause_regress(self, rp):
        """Change some of the above to trigger regress"""
        rp1_1 = rp.append("foo")
        rp1_1.chmod(0o4)
        rp_new = rp.append("lala")
        rp_new.write_string("asoentuh")
        rp_new.chmod(0)
        self.assertEqual(comtst.os_system((b"chown", user.encode(), rp_new.path)), 0)
        rp1_3 = rp.append("unreadable_dir")
        rp1_3.chmod(0o700)
        rp1_3_1 = rp1_3.append("file_inside")
        rp1_3_1.chmod(0o1)
        rp1_3.chmod(0)

        rbdir = rp.append("rdiff-backup-data")
        rbdir.append("current_mirror.2000-12-31T21:33:20-07:00.data").touch()

    def test_backup(self):
        """Test back up, simple restores"""
        in_rp1, in_rp2 = self.make_dirs()
        outrp = rpath.RPath(specifics.local_connection, self.out_dir)
        comtst.re_init_rpath_dir(outrp, userid)
        remote_schema = b'su -c "%s server" %s' % (comtst.RBBin, user.encode())

        cmd1 = (
            comtst.RBBin,
            b"--current-time",
            b"10000",
            b"--remote-schema",
            b"{h}",
            b"backup",
            in_rp1.path,
            b"%b::%b" % (remote_schema, outrp.path),
        )
        self._run_cmd(cmd1)
        in_rp1.setdata()
        outrp.setdata()

        cmd2 = (
            comtst.RBBin,
            b"--current-time",
            b"20000",
            b"--remote-schema",
            b"{h}",
            b"backup",
            in_rp2.path,
            b"%b::%b" % (remote_schema, outrp.path),
        )
        self._run_cmd(cmd2)
        in_rp2.setdata()
        outrp.setdata()

        rout_rp = rpath.RPath(specifics.local_connection, self.restore_dir)
        comtst.remove_dir(rout_rp.path)
        cmd3 = (
            comtst.RBBin,
            b"--remote-schema",
            b"{h}",
            b"restore",
            b"--at",
            b"10000",
            b"%b::%b" % (remote_schema, outrp.path),
            rout_rp.path,
        )
        self._run_cmd(cmd3)
        self.assertTrue(comtst.compare_recursive(in_rp1, rout_rp))
        rout_perms = rout_rp.append("unreadable_dir").getperms()
        outrp_perms = outrp.append("unreadable_dir").getperms()
        self.assertEqual(rout_perms, 0)
        self.assertEqual(outrp_perms, 0)

        comtst.remove_dir(rout_rp.path)
        cmd4 = (
            comtst.RBBin,
            b"--remote-schema",
            b"{h}",
            b"restore",
            b"--at",
            b"now",
            b"%b::%b" % (remote_schema, outrp.path),
            rout_rp.path,
        )
        self._run_cmd(cmd4)
        self.assertTrue(comtst.compare_recursive(in_rp2, rout_rp))
        rout_perms = rout_rp.append("unreadable_dir").getperms()
        outrp_perms = outrp.append("unreadable_dir").getperms()
        self.assertEqual(rout_perms, 0)
        self.assertEqual(outrp_perms, 0)

        self.cause_regress(outrp)
        cmd5 = (
            b"su",
            b"-c",
            b"%s regress %s" % (comtst.RBBin, outrp.path),
            user.encode(),
        )
        self._run_cmd(cmd5, consts.RET_CODE_WARN)


class NonRoot(BaseRootTest):
    """Test backing up as non-root user

    Test backing up a directory with files of different userids and
    with device files in it, as a non-root user.  When restoring as
    root, everything should be restored normally.

    """

    def make_root_dirs(self):
        """Make directory createable only by root"""
        rp = rpath.RPath(
            specifics.local_connection, os.path.join(TEST_BASE_DIR, b"root_out1")
        )
        comtst.re_init_rpath_dir(rp)
        rp1 = rp.append("1")
        rp1.touch()
        rp2 = rp.append("2")
        rp2.touch()
        rp2.chown(1, 1)
        rp3 = rp.append("3")
        rp3.touch()
        rp3.chown(2, 2)
        rp4 = rp.append("dev")
        rp4.makedev("c", 4, 28)

        sp = rpath.RPath(
            specifics.local_connection, os.path.join(TEST_BASE_DIR, b"root_out2")
        )
        if sp.lstat():
            comtst.remove_dir(sp.path)
        comtst.xcopytree(rp.path, sp.path)
        rp2 = sp.append("2")
        rp2.chown(2, 2)
        rp3 = sp.append("3")
        rp3.chown(1, 1)
        self.assertFalse(comtst.compare_recursive(rp, sp, compare_ownership=1))

        return rp, sp

    def backup(self, input_rp, output_rp, time):
        backup_cmd = b"%s --current-time %i backup --no-compare-inode %b %b" % (
            comtst.RBBin,
            time,
            input_rp.path,
            output_rp.path,
        )
        self._run_cmd((b"su", user.encode(), b"-c", backup_cmd))

    def restore(self, dest_rp, restore_rp, time=None):
        comtst.remove_dir(restore_rp.path)
        if time is None or time == "now":
            restore_cmd = (
                comtst.RBBin,
                b"restore",
                b"--at",
                b"now",
                dest_rp.path,
                restore_rp.path,
            )
        else:
            restore_cmd = (
                comtst.RBBin,
                b"restore",
                b"--at",
                b"%i" % time,
                dest_rp.path,
                restore_rp.path,
            )
        self._run_cmd(restore_cmd)

    def test_non_root(self):
        """Main non-root -> root test"""
        input_rp1, input_rp2 = self.make_root_dirs()
        generics.change_ownership = 1
        output_rp = rpath.RPath(specifics.local_connection, self.out_dir)
        comtst.re_init_rpath_dir(output_rp, userid)
        restore_rp = rpath.RPath(specifics.local_connection, self.restore_dir)
        empty_rp = rpath.RPath(
            specifics.local_connection, os.path.join(comtst.old_test_dir, b"empty")
        )

        self.backup(input_rp1, output_rp, 1000000)
        self.restore(output_rp, restore_rp)
        self.assertTrue(
            comtst.compare_recursive(input_rp1, restore_rp, compare_ownership=1)
        )

        self.backup(input_rp2, output_rp, 2000000)
        self.restore(output_rp, restore_rp)
        self.assertTrue(
            comtst.compare_recursive(input_rp2, restore_rp, compare_ownership=1)
        )

        self.backup(empty_rp, output_rp, 3000000)
        self.restore(output_rp, restore_rp)
        self.assertTrue(
            comtst.compare_recursive(empty_rp, restore_rp, compare_ownership=1)
        )

        self.restore(output_rp, restore_rp, 1000000)
        self.assertTrue(
            comtst.compare_recursive(input_rp1, restore_rp, compare_ownership=1)
        )

        self.restore(output_rp, restore_rp, 2000000)
        self.assertTrue(
            comtst.compare_recursive(input_rp2, restore_rp, compare_ownership=1)
        )


if __name__ == "__main__":
    unittest.main()
