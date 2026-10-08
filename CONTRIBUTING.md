# Contributing

Thanks for your interest. spirotrace is in early development; issues and suggestions are welcome.

## Never share patient data

Do not attach reports, screenshots of reports, extracted values or corrections files to issues or pull requests, even if you think they are de-identified. To report a layout that is not read correctly, use the "Layout not read" issue template and attach only the masked, structure-only survey output.

## Development

```
git clone https://github.com/hawkek/spirotrace
cd spirotrace
python -m pip install -e ".[dev]"
python -m pytest
```

- One change per pull request, with tests. A bug fix starts with a test that fails without the fix.
- Test data is synthetic: generated in the tests, never real reports.
- Layout templates describe geometry and vocabulary only. Behaviour that a layout needs goes into a named, tested Python handler that the template switches on.

## Support

This is a research tool maintained alongside a PhD. Issues are read, but responses may take a while.
