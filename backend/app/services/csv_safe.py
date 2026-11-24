"""
Spreadsheet safe CSV cells.

A cell that starts with = + - @ a tab or a carriage return is read by a spreadsheet as a formula, so text a machine or a person
chose (a device name, a node type, an audit detail) could run one when an export is opened. Such a text cell gets a single quote
in front, which the spreadsheet shows as nothing and which stops the formula. Numbers, booleans and dates are not text and pass
unchanged (a negative number is written by the csv module as a number and is not a formula).
"""

_DANGEROUS_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    if isinstance(value, str) and value.startswith(_DANGEROUS_START):
        return "'" + value
    return value


def safe_row(values) -> list:
    return [safe_cell(v) for v in values]
