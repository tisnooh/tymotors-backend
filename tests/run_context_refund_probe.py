"""Use the existing owned-process harness with a dedicated refund probe."""
import sys

from tests import run_commerce_pipeline


def main():
    # Existing harness still validates free loopback ports and owns teardown.
    sys.argv.extend(['--probe-module', 'tests.commerce_context_refund_probe'])
    run_commerce_pipeline.main()


if __name__ == '__main__': main()
