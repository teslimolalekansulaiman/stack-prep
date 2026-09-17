"""Engine version, stamped on every derived record.

Bump this whenever a rule changes in a way that would alter a student's ratings,
plans or recommendations. Derived state is rebuilt by replaying events under a
known version, so this string is part of the data, not just the code.
"""

ENGINE_VERSION = "0.2.0"
