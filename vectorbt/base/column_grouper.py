"""Class that exposes methods to group columns."""

import numpy as np
import pandas as pd
from numba import njit

from vectorbt.utils import checks
from vectorbt.utils.decorators import cached_method
from vectorbt.utils.array import is_sorted
from vectorbt.utils.config import Configured
from vectorbt.base import index_fns


def group_by_to_index(index, group_by):
    """Convert mapper `group_by` to `pd.Index`.

    !!! note
        Index and mapper must have the same length."""
    if group_by is None or isinstance(group_by, bool):
        return group_by

    if isinstance(group_by, (int, str, tuple, list)):
        group_by = index_fns.select_levels(index, group_by)
    if not isinstance(group_by, pd.Index):
        group_by = pd.Index(group_by)
    if len(group_by) != len(index):
        raise ValueError("group_by and index must have the same length")
    return group_by


def get_groups_and_index(index, group_by):
    """Return array of group indices pointing to the original index, and grouped index.
    """
    if group_by is None or isinstance(group_by, bool):
        return np.arange(len(index)), index

    group_by = group_by_to_index(index, group_by)
    groups, index = pd.factorize(group_by)
    if not isinstance(index, pd.Index):
        index = pd.Index(index)
    if isinstance(group_by, pd.MultiIndex):
        index.names = group_by.names
    elif isinstance(group_by, (pd.Index, pd.Series)):
        index.name = group_by.name
    if not is_sorted(groups):
        raise ValueError("Groups must be coherent and sorted")
    return groups, index


@njit(cache=True)
def get_group_counts_nb(groups):
    """Return count per group."""
    result = np.empty(groups.shape[0], dtype=np.int_)
    j = 0
    prev_group = -1
    run_count = 0
    for i in range(groups.shape[0]):
        cur_group = groups[i]
        if cur_group < prev_group:
            raise ValueError("Groups must be coherent and sorted")
        if cur_group != prev_group:
            if prev_group != -1:
                # Process previous group
                result[j] = run_count
                j += 1
                run_count = 0
            prev_group = cur_group
        run_count += 1
        if i == groups.shape[0] - 1:
            # Process last group
            result[j] = run_count
            j += 1
            run_count = 0
    return result[:j]


class ColumnGrouper(Configured):
    """Class that exposes methods to group columns.

    `group_by` can be integer (level by position), string (level by name), tuple or list
    (multiple levels), index or series (named index with groups), or NumPy array (raw groups).

    Set `allow_enable` to False to prohibit grouping if `ColumnGrouper.group_by` is None.
    Set `allow_disable` to False to prohibit disabling of grouping if `ColumnGrouper.group_by` is not None.
    Set `allow_modify` to False to prohibit changing groups (you can still change their labels).

    All properties are read-only to enable caching.

    !!! note
        Columns must build groups that are coherent and sorted.

    !!! note
        This class is meant to be immutable. To change any attribute, use `ColumnGrouper.copy`."""

    def __init__(self, columns, group_by=None, allow_enable=True, allow_disable=True, allow_modify=True):
        Configured.__init__(
            self,
            columns=columns,
            group_by=group_by,
            allow_enable=allow_enable,
            allow_disable=allow_disable,
            allow_modify=allow_modify
        )

        checks.assert_not_none(columns)
        self._columns = columns
        if group_by is None or isinstance(group_by, bool):
            self._group_by = None
        else:
            self._group_by = group_by_to_index(columns, group_by)

        # Everything is allowed by default
        self._allow_enable = allow_enable
        self._allow_disable = allow_disable
        self._allow_modify = allow_modify

    @property
    def columns(self):
        """Original columns."""
        return self._columns

    @property
    def group_by(self):
        """Mapper for grouping."""
        return self._group_by

    @property
    def allow_enable(self):
        """Whether to allow enabling grouping."""
        return self._allow_enable

    @property
    def allow_disable(self):
        """Whether to allow disabling grouping."""
        return self._allow_disable

    @property
    def allow_modify(self):
        """Whether to allow changing groups."""
        return self._allow_modify

    def is_grouped(self, group_by=None):
        """Check whether columns are grouped."""
        if group_by is False:
            return False
        if group_by is None or group_by is True:
            group_by = self.group_by
        return group_by is not None

    def is_grouping_enabled(self, group_by=None):
        """Check whether column grouping has been enabled."""
        return self.group_by is None and self.is_grouped(group_by=group_by)

    def is_grouping_disabled(self, group_by=None):
        """Check whether column grouping has been disabled."""
        return self.group_by is not None and not self.is_grouped(group_by=group_by)

    def is_grouping_modified(self, group_by=None):
        """Check whether column grouping has been modified."""
        group_by = group_by_to_index(self.columns, group_by)
        if isinstance(group_by, pd.Index) and isinstance(self.group_by, pd.Index):
            if not pd.Index.equals(group_by, self.group_by):
                groups1 = get_groups_and_index(self.columns, group_by)[0]
                groups2 = get_groups_and_index(self.columns, self.group_by)[0]
                if not np.array_equal(groups1, groups2):
                    return True
        return False

    def is_grouping_changed(self, group_by=None):
        """Check whether column grouping has been changed."""
        return self.is_grouping_enabled(group_by=group_by) \
            or self.is_grouping_disabled(group_by=group_by) \
            or self.is_grouping_modified(group_by=group_by)

    def check_group_by(self, group_by=None, allow_enable=None, allow_disable=None, allow_modify=None):
        """Check passed `group_by` object against restrictions."""
        if allow_enable is None:
            allow_enable = self.allow_enable
        if allow_disable is None:
            allow_disable = self.allow_disable
        if allow_modify is None:
            allow_modify = self.allow_modify

        if not allow_enable and self.is_grouping_enabled(group_by=group_by):
            raise ValueError("Enabling grouping is not allowed")
        if not allow_disable and self.is_grouping_disabled(group_by=group_by):
            raise ValueError("Disabling grouping is not allowed")
        if not allow_modify and self.is_grouping_modified(group_by=group_by):
            raise ValueError("Changing groups is not allowed")

    def resolve_group_by(self, group_by=None, **kwargs):
        """Resolve `group_by` from either object variable or keyword argument."""
        if group_by is None or group_by is True:
            group_by = self.group_by
        if group_by is False and self.group_by is None:
            group_by = None
        self.check_group_by(group_by=group_by, **kwargs)
        return group_by_to_index(self.columns, group_by)

    @cached_method
    def get_groups_and_columns(self, **kwargs):
        """See `get_groups_and_index`."""
        group_by = self.resolve_group_by(**kwargs)
        return get_groups_and_index(self.columns, group_by)

    def get_groups(self, **kwargs):
        """Return groups array."""
        return self.get_groups_and_columns(**kwargs)[0]

    def get_columns(self, **kwargs):
        """Return grouped columns."""
        return self.get_groups_and_columns(**kwargs)[1]

    @cached_method
    def get_group_counts(self, **kwargs):
        """See get_group_counts_nb."""
        group_by = self.resolve_group_by(**kwargs)
        if group_by is None or group_by is False:  # no grouping
            return np.full(len(self.columns), 1)
        groups = self.get_groups(**kwargs)
        return get_group_counts_nb(groups)

    @cached_method
    def get_group_start_idxs(self, **kwargs):
        """Get first index of each group as an array."""
        group_counts = self.get_group_counts(**kwargs)
        return np.cumsum(group_counts) - group_counts

    @cached_method
    def get_group_end_idxs(self, **kwargs):
        """Get end index of each group as an array."""
        group_counts = self.get_group_counts(**kwargs)
        return np.cumsum(group_counts)
