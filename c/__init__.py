# Lazy imports to avoid requiring Pyomo at package load time.
# Use: from c.config import ModelParams  (no Pyomo needed)
# Use: from c.run import run_fansi        (needs Pyomo)

from c.config import ModelParams, MODULES, MODULE_RANGE
