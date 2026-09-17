"""Experiment runner script: executes experiments defined by YAML configurations."""

from __future__ import annotations

import argparse
import logging
import sys
from xlmem.config import ExperimentConfig
from xlmem.runner.experiment import ExperimentRunner

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("run")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an XLMem experiment from config.")
    parser.add_argument("--config", required=True, help="Path to experiment YAML configuration.")
    args = parser.parse_args()

    logger.info("Loading config from %s", args.config)
    config = ExperimentConfig.from_yaml(args.config)
    runner = ExperimentRunner(config=config)

    logger.info("Launching experiment: %s across seeds %s", config.experiment, config.seeds)
    run_dirs = runner.run_all_seeds()
    logger.info("Experiment %s complete. Output directories: %s", config.experiment, [str(p) for p in run_dirs])
    return 0


if __name__ == "__main__":
    sys.exit(main())
