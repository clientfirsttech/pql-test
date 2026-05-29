# Epic: Format Test Results for Human Readability

**Issue:** #30  
**Branch:** fix-30-format-test-results  
**Status:** In Progress  
**Created:** 2026-05-29

## Goal

Improve the human readability of test result output in the `pql-test run-tests` command by enhancing visual formatting, adding more contextual information, and making the output easier to scan and understand.

## User Story

As a Power BI developer running DAX tests, I want test results to be clearly formatted with visual indicators, timing information, and organized sections so that I can quickly understand test outcomes without parsing dense output.

## Current State

The existing `_print_results()` function in `python/pql_test/cli.py` provides basic pytest-style output with:
- Simple text-based status indicators (PASS, FAIL, SKIP)
- Dot notation for compact mode
- Failures and warnings sections
- Basic summary line

## Proposed Changes

### Enhanced Output Features

1. **Visual Improvements**
   - Add Unicode icons (✓, ✗, ⊘) for pass/fail/skip status
   - Use bold text for test names and status indicators
   - Add numbered counters for failures [1/3] and warnings [1]
   - Group dots every 10 tests for easier counting

2. **Timing Information**
   - Calculate and display total test duration
   - Show duration in brackets [125ms] for each test in verbose mode
   - Format large durations as seconds (e.g., "2.45s" instead of "2450ms")

3. **Enhanced Header**
   - Change "test session starts" to uppercase "TEST SESSION STARTS"
   - Add cyan color to header separator
   - Display total test count in header
   - Bold the model path for emphasis

4. **Better Error Context**
   - Add labeled fields: "Message:", "Error:", "Expected:", "Actual:"
   - Use color coding for different field types (yellow for message, red for error, cyan for expected/actual)
   - Show failure counter [1/3] for each failed test

5. **Enhanced Summary**
   - Calculate and display pass rate percentage (e.g., "95.0% pass rate")
   - Color-code pass rate: green (100%), yellow (≥80%), red (<80%)
   - Color individual stats (green for passed, red for failed, yellow for warnings)
   - Show overall status: "PASSED", "FAILED", or "PASSED WITH WARNINGS"
   - Include total duration at end of summary

6. **Improved Readability**
   - In verbose mode, show failure messages on separate lines with arrow indicator (→)
   - Add extra blank line at end of output
   - Use consistent separator style (all "=" instead of mix of "=" and "-")

## Files Modified

- `python/pql_test/cli.py` - Enhanced `_print_results()` function

## Testing Strategy

- Verify output with existing example models
- Check both verbose and compact modes
- Ensure colors and icons display correctly
- Validate timing calculations
- Test with passing, failing, and skipped tests

## Success Criteria

- [ ] Test output includes visual icons for status
- [ ] Total duration and pass rate are displayed
- [ ] Failure details show labeled fields (Message, Error, Expected, Actual)
- [ ] Compact mode groups dots every 10 tests
- [ ] Summary shows colored stats and overall status
- [ ] Existing tests continue to pass
- [ ] Output is more readable at a glance

## Notes

- Unicode icons (✓, ✗, ⊘) are widely supported in modern terminals
- Changes are backward compatible - no breaking changes to output format
- Enhanced formatting applies to standard output only; JSON output unchanged
- Azure DevOps and GitHub Actions formatters remain unchanged
