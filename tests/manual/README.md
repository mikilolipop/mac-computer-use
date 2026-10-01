# Historical desktop probes

The `.py.disabled` files preserve the original desktop test scripts for reference.
They are excluded from default Python/pytest discovery because they activate real
apps, overwrite the clipboard, and type into the current foreground window.

Do not rename and run them as a regression suite. They also contain outdated tool
counts and preflight expectations. Future live tests must use a dedicated fixture
application, explicit target identity, bounded subprocesses, and state cleanup.

Default safe suite (no desktop input):

```sh
python3 -m unittest discover -s tests -p 'test_safety.py' -v
python3 tests/test_boost_coordinator.py
```
