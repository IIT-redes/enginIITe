"""Names of the solver statuses.

Gurobi 11 offered a class in ``gurobipy`` that held every status constant, and Gurobi 12 removed it. The constants are
still attributes of ``GRB`` in both versions, so the table is built from the list of status names below. Other
numeric constants of ``GRB`` cannot be scanned for it, because some share the number of a status.
"""
from gurobipy import GRB

_STATUS_NAMES = ('LOADED', 'OPTIMAL', 'INFEASIBLE', 'INF_OR_UNBD', 'UNBOUNDED', 'CUTOFF', 'ITERATION_LIMIT',
                 'NODE_LIMIT', 'TIME_LIMIT', 'SOLUTION_LIMIT', 'INTERRUPTED', 'NUMERIC', 'SUBOPTIMAL', 'INPROGRESS',
                 'USER_OBJ_LIMIT', 'WORK_LIMIT', 'MEM_LIMIT')


def status_names():
    """Return ``{status code: status name}`` for the statuses that this version of Gurobi defines."""
    return {getattr(GRB, name): name for name in _STATUS_NAMES if hasattr(GRB, name)}


def status_name(code):
    """Name of a status code, or a readable text when the code is not known."""
    return status_names().get(code, f'status {code}')
