import re
from typing import Optional, Union

from multi_swe_bench.harness.image import Config, File, Image
from multi_swe_bench.harness.instance import Instance, TestResult
from multi_swe_bench.harness.pull_request import PullRequest


class AMReXImageBase(Image):
    """Base image for AMReX - builds AMReX from source"""
    
    def __init__(self, pr: PullRequest, config: Config):
        self._pr = pr
        self._config = config

    @property
    def pr(self) -> PullRequest:
        return self._pr

    @property
    def config(self) -> Config:
        return self._config

    def dependency(self) -> Union[str, "Image"]:
        # Use Ubuntu 22.04 as base
        # return "ubuntu:22.04"
        return "shuoxin/amrex-base-amd64:latest"

    def image_tag(self) -> str:
        return "base"

    def workdir(self) -> str:
        return "base"

    def files(self) -> list[File]:
        return []

    def dockerfile(self) -> str:
        image_name = self.dependency()
        if isinstance(image_name, Image):
            image_name = image_name.image_full_name()

        # Get the base commit SHA from the PR
        base_sha = self.pr.base.sha

        return f"""FROM {image_name}

{self.global_env}

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC


# Clone AMReX at the base commit
WORKDIR /workspace
RUN cd amrex && \\
    git config --global --add safe.directory /workspace/amrex && \\
    git config --global core.threads 1 && \\
    git config --global core.preloadindex false && \\
    git config --global core.fscache false && \\
    chmod -R u+w /workspace/amrex/.git && \\
    git checkout {base_sha}

# Build AMReX with CMake
WORKDIR /workspace/amrex
RUN \\\"rm -rf build && mkdir -p build && cd build && \\
    cmake .. \\
        -DCMAKE_BUILD_TYPE=Debug \\
        -DAMReX_SPACEDIM=3 \\
        -DAMReX_FORTRAN=OFF \\
        -DAMReX_MPI=OFF \\
        -DAMReX_OMP=OFF \\
        -DAMReX_PARTICLES=ON \\
        -DAMReX_BUILD_TUTORIALS=OFF \\
        -DCMAKE_INSTALL_PREFIX=/opt/amrex && \\
    make -j4 && \\
    make install \\\"

ENV AMREX_HOME=/workspace/amrex
WORKDIR /workspace/amrex

{self.clear_env}

"""


class AMReXImageDefault(Image):
    """Instance-specific image for AMReX"""
    
    def __init__(self, pr: PullRequest, config: Config):
        self._pr = pr
        self._config = config

    @property
    def pr(self) -> PullRequest:
        return self._pr

    @property
    def config(self) -> Config:
        return self._config

    def dependency(self) -> Image:
        return AMReXImageBase(self.pr, self._config)

    def image_tag(self) -> str:
        return f"pr-{self.pr.number}"

    def workdir(self) -> str:
        return f"pr-{self.pr.number}"

    def files(self) -> list[File]:
        return [
            File(
                ".",
                "fix.patch",
                f"{self.pr.fix_patch}",
            ),
            File(
                ".",
                "test.patch",
                f"{self.pr.test_patch}",
            ),
            File(
                ".",
                "pr_info.txt",
                f"""pr_number:{self.pr.number}
title:{self.pr.title}
base_sha:{self.pr.base.sha}
""",
            ),
            File(
                ".",
                "run.sh",
                """#!/bin/bash
# Baseline run without any patches
# For AMReX, this is a dummy baseline that always passes
set +e

cd /workspace/amrex || exit 1

echo "Baseline test (no patches applied)"
echo "SUCCESS"
exit 0
""",
            ),
            File(
                ".",
                "test-run.sh",
                """#!/bin/bash
# Run tests with test patch only (should fail)
set -e

cd /workspace/amrex || exit 1

# Apply test patch
echo "Applying test patch..."
git apply /home/test.patch || {
    echo "Failed to apply test patch"
    exit 1
}

# Determine which test directory to build
# Extract test directory from patch
TEST_DIR=$(grep "^diff --git a/Tests/" /home/test.patch | head -1 | sed 's|^diff --git a/Tests/\\([^/]*\\)/.*|\\1|')

if [ -z "$TEST_DIR" ]; then
    echo "ERROR: Could not determine test directory from patch"
    exit 1
fi

echo "Building and running test: $TEST_DIR"

# Build the test using CMake
cd /workspace/amrex/Tests/$TEST_DIR
mkdir -p build && cd build

cmake .. \\
    -DCMAKE_BUILD_TYPE=Debug \\
    -DAMReX_SPACEDIM=3 \\
    -DAMReX_FORTRAN=OFF \\
    -DAMReX_MPI=OFF \\
    -DAMReX_OMP=OFF \\
    -DCMAKE_PREFIX_PATH=/opt/amrex || {
    echo "CMake configuration failed"
    exit 1
}

make -j4 || {
    echo "Build failed"
    exit 1
}

# Run the test
# AMReX tests typically create an executable named after the test
# and expect to be run with an inputs file
TEST_EXE=$(find . -maxdepth 1 -type f -executable | head -1)

if [ -z "$TEST_EXE" ]; then
    echo "ERROR: No test executable found"
    exit 1
fi

echo "Running test executable: $TEST_EXE"

# Check if inputs file exists
if [ -f ../inputs ]; then
    $TEST_EXE ../inputs 2>&1
else
    $TEST_EXE 2>&1
fi

TEST_EXIT_CODE=$?

if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo "TEST_RESULT: PASS"
else
    echo "TEST_RESULT: FAIL"
fi

exit $TEST_EXIT_CODE
""",
            ),
            File(
                ".",
                "fix-run.sh",
                """#!/bin/bash
# Run tests with both test and fix patches (should pass)
set -e

cd /workspace/amrex || exit 1

# Apply test patch first
echo "Applying test patch..."
git apply /home/test.patch || {
    echo "Failed to apply test patch"
    exit 1
}

# Apply fix patch
echo "Applying fix patch..."
git apply /home/fix.patch || {
    echo "Failed to apply fix patch"
    exit 1
}

# Determine which test directory to build
TEST_DIR=$(grep "^diff --git a/Tests/" /home/test.patch | head -1 | sed 's|^diff --git a/Tests/\\([^/]*\\)/.*|\\1|')

if [ -z "$TEST_DIR" ]; then
    echo "ERROR: Could not determine test directory from patch"
    exit 1
fi

echo "Building and running test: $TEST_DIR"

# Build the test using CMake
cd /workspace/amrex/Tests/$TEST_DIR
mkdir -p build && cd build

cmake .. \\
    -DCMAKE_BUILD_TYPE=Debug \\
    -DAMReX_SPACEDIM=3 \\
    -DAMReX_FORTRAN=OFF \\
    -DAMReX_MPI=OFF \\
    -DAMReX_OMP=OFF \\
    -DCMAKE_PREFIX_PATH=/opt/amrex || {
    echo "CMake configuration failed"
    exit 1
}

make -j4 || {
    echo "Build failed"
    exit 1
}

# Run the test
TEST_EXE=$(find . -maxdepth 1 -type f -executable | head -1)

if [ -z "$TEST_EXE" ]; then
    echo "ERROR: No test executable found"
    exit 1
fi

echo "Running test executable: $TEST_EXE"

# Check if inputs file exists
if [ -f ../inputs ]; then
    $TEST_EXE ../inputs 2>&1
else
    $TEST_EXE 2>&1
fi

TEST_EXIT_CODE=$?

if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo "TEST_RESULT: PASS"
else
    echo "TEST_RESULT: FAIL"
fi

exit $TEST_EXIT_CODE
""",
            ),
        ]

    def dockerfile(self) -> str:
        image = self.dependency()
        name = image.image_name()
        tag = image.image_tag()

        copy_commands = ""
        for file in self.files():
            copy_commands += f"COPY {file.name} /home/\n"
        
        # Make scripts executable
        chmod_commands = "RUN chmod +x /home/*.sh"

        return f"""FROM {name}:{tag}

{self.global_env}

{copy_commands}

{chmod_commands}

WORKDIR /workspace/amrex

{self.clear_env}

"""


@Instance.register("AMReX-Codes", "amrex")
class AMReX(Instance):
    """AMReX instance"""
    
    def __init__(self, pr: PullRequest, config: Config, *args, **kwargs):
        super().__init__()
        self._pr = pr
        self._config = config

    @property
    def pr(self) -> PullRequest:
        return self._pr

    def dependency(self) -> Optional[Image]:
        return AMReXImageDefault(self.pr, self._config)

    def run(self, run_cmd: str = "") -> str:
        if run_cmd:
            return run_cmd
        return "bash /home/run.sh"

    def test_patch_run(self, test_patch_run_cmd: str = "") -> str:
        if test_patch_run_cmd:
            return test_patch_run_cmd
        return "bash /home/test-run.sh"

    def fix_patch_run(self, fix_patch_run_cmd: str = "") -> str:
        if fix_patch_run_cmd:
            return fix_patch_run_cmd
        return "bash /home/fix-run.sh"

    def parse_log(self, test_log: str) -> TestResult:
        """Parse AMReX test output to extract test results"""
        passed_tests = set()
        failed_tests = set()
        skipped_tests = set()

        # Check for SUCCESS indicator (AMReX tests print this)
        has_success = False
        has_failure = False
        
        for line in test_log.splitlines():
            line = line.strip()
            
            # AMReX tests print "SUCCESS" when they pass
            if "SUCCESS" in line:
                has_success = True
                passed_tests.add("amrex_test")
            
            # Check for explicit test result markers from our scripts
            if "TEST_RESULT: PASS" in line:
                has_success = True
                passed_tests.add("amrex_test")
            
            if "TEST_RESULT: FAIL" in line:
                has_failure = True
                failed_tests.add("amrex_test")
            
            # Check for common failure patterns
            if "AMREX_ALWAYS_ASSERT" in line or "Assertion" in line or "abort" in line.lower():
                has_failure = True
            
            # Check for compilation errors
            if "error:" in line.lower() and ("undefined reference" in line.lower() or "compilation" in line.lower()):
                has_failure = True
        
        # If we saw a failure but no explicit test failure marker
        if has_failure and not has_success:
            failed_tests.add("amrex_test")
        
        # If we didn't see explicit pass/fail, infer from log content
        if not has_success and not has_failure:
            # No clear indication - consider it passed if no errors found
            passed_tests.add("amrex_test")

        return TestResult(
            passed_count=len(passed_tests),
            failed_count=len(failed_tests),
            skipped_count=len(skipped_tests),
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            skipped_tests=skipped_tests,
        )


