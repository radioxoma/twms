#!/usr/bin/env python

import doctest
import unittest

from twms import __main__, api, bbox, config, fetchers, projections, twms

modules = (api, config, projections, twms, bbox, fetchers, __main__)


def load_tests(loader: unittest.TestLoader, tests, pattern) -> unittest.TestSuite:
    """Callback to load doctests from modules."""
    tests.addTests([doctest.DocTestSuite(m) for m in modules])
    return tests
