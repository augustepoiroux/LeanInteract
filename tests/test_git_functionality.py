import shutil
import tempfile
import unittest
from pathlib import Path

import git

from lean_interact.project import GitProject
from lean_interact.utils import _GitUtilities


def resolve_path(path):
    """Resolve path to handle symlinks on different platforms (especially macOS)."""
    return Path(path).resolve()


class TestGitProject(unittest.TestCase):
    """Tests for GitProject using git repositories."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache_dir = resolve_path(self.temp_dir) / "cache"
        self.repo_dir = resolve_path(self.temp_dir) / "repo"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.repo_dir.mkdir(parents=True, exist_ok=True)

        # Create a git repository with multiple commits and branches
        self.repo = git.Repo.init(self.repo_dir)

        # Initial commit on main
        (self.repo_dir / "lean-toolchain").write_text("leanprover/lean4:v4.14.0\n")
        (self.repo_dir / "lakefile.lean").write_text('import Lake\nopen Lake DSL\n\npackage "test" where\n')
        (self.repo_dir / "Test.lean").write_text('-- Test file\ndef hello : String := "world"\n')
        self.repo.index.add(
            [
                str(self.repo_dir / "lean-toolchain"),
                str(self.repo_dir / "lakefile.lean"),
                str(self.repo_dir / "Test.lean"),
            ]
        )
        initial_commit = self.repo.index.commit("Initial commit with Lean project")

        # Create main branch explicitly (git init doesn't create it until first commit)
        main_branch = self.repo.create_head("main", initial_commit.hexsha)
        self.repo.head.reference = main_branch

        # Create a feature branch with additional commits
        feature_branch = self.repo.create_head("feature/new-def")
        feature_branch.checkout()
        (self.repo_dir / "Test.lean").write_text(
            '-- Test file\ndef hello : String := "world"\ndef greet : String := "Hello, " ++ hello\n'
        )
        self.repo.index.add([str(self.repo_dir / "Test.lean")])
        self.repo.index.commit("Add greet function")

        # Create a tag
        self.repo.create_tag("v1.0.0")

        # Switch back to main and add another commit
        main_branch.checkout()
        (self.repo_dir / "README.md").write_text("# Test Lean Project\n")
        self.repo.index.add([str(self.repo_dir / "README.md")])
        self.repo.index.commit("Add README")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_git_project_clone_and_build(self):
        """Test GitProject cloning and building a repository."""
        git_url = f"file://{self.repo_dir}"
        git_project = GitProject(url=git_url)

        project_dir = Path(git_project.get_directory())
        self.assertTrue(project_dir.exists())
        self.assertTrue((project_dir / "lean-toolchain").exists())
        self.assertTrue((project_dir / "Test.lean").exists())

    def test_git_project_with_specific_revision(self):
        """Test GitProject with a specific revision (tag)."""
        git_url = f"file://{self.repo_dir}"
        git_project = GitProject(url=git_url, rev="v1.0.0")

        project_dir = git_project.get_directory()
        # Verify we're on the correct revision
        repo = git.Repo(project_dir)
        self.assertEqual(repo.head.commit, repo.tags["v1.0.0"].commit)

    def test_git_project_with_branch_revision(self):
        """Test GitProject with a specific branch."""
        git_url = f"file://{self.repo_dir}"
        git_project = GitProject(url=git_url, rev="feature/new-def")

        project_dir = Path(git_project.get_directory())
        # Verify we have the greet function from the feature branch
        test_content = (project_dir / "Test.lean").read_text()
        self.assertIn("greet", test_content)

    def test_git_project_force_pull(self):
        """Test GitProject with force_pull enabled."""
        git_url = f"file://{self.repo_dir}"
        git_project = GitProject(url=git_url)

        project_dir = Path(git_project.get_directory())

        # Make changes to the original repo
        (self.repo_dir / "NewFile.lean").write_text("-- New file\ndef newFunction : Nat := 42\n")
        self.repo.index.add([str(self.repo_dir / "NewFile.lean")])
        self.repo.index.commit("Add new file")

        self.assertFalse((project_dir / "NewFile.lean").exists())

        git_project = GitProject(url=git_url, force_pull=True)

        # Should have the new file after force pull
        self.assertTrue((project_dir / "NewFile.lean").exists())

    def test_git_project_update_existing_repo(self):
        """Test updating an existing GitProject repository."""
        git_url = f"file://{self.repo_dir}"
        git_project = GitProject(url=git_url)

        project_dir = Path(git_project.get_directory())
        initial_commit = git.Repo(project_dir).head.commit.hexsha

        # Make changes to original repo
        (self.repo_dir / "Update.lean").write_text("-- Updated file\n")
        self.repo.index.add([str(self.repo_dir / "Update.lean")])
        self.repo.index.commit("Update for test")

        self.assertFalse((project_dir / "Update.lean").exists())

        # Second instantiation should update
        git_project = GitProject(url=git_url)

        # Should have pulled the update
        final_commit = git.Repo(project_dir).head.commit.hexsha
        self.assertNotEqual(initial_commit, final_commit)
        self.assertTrue((project_dir / "Update.lean").exists())


class TestGitUtilities(unittest.TestCase):
    """Tests for _GitUtilities using git repositories."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_dir = resolve_path(self.temp_dir) / "repo"
        self.repo_dir.mkdir(parents=True, exist_ok=True)

        # Create a git repository
        self.repo = git.Repo.init(self.repo_dir)
        (self.repo_dir / "README.md").write_text("# Test Repo\n")
        self.repo.index.add([str(self.repo_dir / "README.md")])
        initial_commit = self.repo.index.commit("Initial commit")

        # Create main branch
        main_branch = self.repo.create_head("main", initial_commit.hexsha)
        self.repo.head.reference = main_branch

        # Create feature branch
        feature_branch = self.repo.create_head("feature/test")
        feature_branch.checkout()
        (self.repo_dir / "feature.txt").write_text("feature content\n")
        self.repo.index.add([str(self.repo_dir / "feature.txt")])
        self.repo.index.commit("Add feature")

        # Go back to main
        main_branch.checkout()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_git_utilities_branch_operations(self):
        """Test _GitUtilities branch-related operations."""
        git_utils = _GitUtilities(str(self.repo_dir))

        # Test getting current branch
        self.assertEqual(git_utils.get_current_branch_name(), "main")

        # Test checking if branch exists
        self.assertTrue(git_utils.branch_exists_locally("main"))
        self.assertTrue(git_utils.branch_exists_locally("feature/test"))
        self.assertFalse(git_utils.branch_exists_locally("nonexistent"))

        # Test safe checkout
        self.assertTrue(git_utils.safe_checkout("feature/test"))
        self.assertEqual(git_utils.get_current_branch_name(), "feature/test")

        # Test safe checkout back to main
        self.assertTrue(git_utils.safe_checkout("main"))
        self.assertEqual(git_utils.get_current_branch_name(), "main")

    def test_git_utilities_fetch_and_reset(self):
        """Test _GitUtilities fetch and reset operations."""
        # Create a clone to simulate remote operations
        clone_dir = resolve_path(self.temp_dir) / "clone"
        self.repo.clone(clone_dir)
        clone_utils = _GitUtilities(str(clone_dir))

        # Make changes in original repo
        (self.repo_dir / "new_file.txt").write_text("new content\n")
        self.repo.index.add([str(self.repo_dir / "new_file.txt")])
        self.repo.index.commit("Add new file")

        # Test that reset operations don't crash
        result = clone_utils.safe_reset_hard("HEAD")
        self.assertTrue(result)

        # Test that submodule operations don't crash (no submodules, so should succeed trivially)
        result = clone_utils.update_submodules()
        self.assertTrue(result)


class TestLeanREPLConfigIntegration(unittest.TestCase):
    """Integration test for LeanREPLConfig with GitProject."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache_dir = resolve_path(self.temp_dir) / "cache"
        self.project_repo_dir = resolve_path(self.temp_dir) / "project_repo"

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.project_repo_dir.mkdir(parents=True, exist_ok=True)

        # Create a Lean project repository
        self.project_repo = git.Repo.init(self.project_repo_dir)
        (self.project_repo_dir / "Test.lean").write_text('-- Test project\ndef test : String := "hello"\n')
        (self.project_repo_dir / "lakefile.lean").write_text('import Lake\nopen Lake DSL\n\npackage "test" where\n')
        (self.project_repo_dir / "lean-toolchain").write_text("leanprover/lean4:v4.14.0\n")
        self.project_repo.index.add(
            [
                str(self.project_repo_dir / "Test.lean"),
                str(self.project_repo_dir / "lakefile.lean"),
                str(self.project_repo_dir / "lean-toolchain"),
            ]
        )
        self.project_repo.index.commit("Initial project commit")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_lean_repl_config_version_inference_from_git_project(self):
        """Test that LeanREPLConfig correctly infers Lean version from a GitProject."""
        from lean_interact.config import LeanREPLConfig

        project_git_url = f"file://{self.project_repo_dir}"

        config = LeanREPLConfig(
            project=GitProject(url=project_git_url),
            cache_dir=self.cache_dir,
            verbose=True,
        )

        # Should have correctly inferred the version from the project's lean-toolchain
        self.assertEqual(config.lean_version, "v4.14.0")

        # Should have cloned and set up the project directory
        self.assertTrue(Path(config.working_dir).exists())
        self.assertTrue((Path(config.working_dir) / "Test.lean").exists())
        self.assertTrue((Path(config.working_dir) / "lean-toolchain").exists())


if __name__ == "__main__":
    unittest.main()
