# Cook integration tests


Integration tests for Cook scheduler

To run the tests on a local cook install, run

```bash
$ python setup.py nosetests
```

To configure the Cook scheduler URL, set the `COOK_SCHEDULER_URL` environment variable. The default value is `http://localhost:12321`.

If you want to run a single test and see the log messages as they occur, you can run, for example:

```bash
$ nosetests tests.cook.test_basic:CookTest.test_max_runtime_exceeded --nologcapture
```

## Multi-scheduler tests

The [test_multi_cook.py](tests/cook/test_multi_cook.py) file contains integration tests that rely on two separate running schedulers. These tests are skipped by default, since we often only want to target a single cook cluster. If you want to include these tests, make sure to set the `COOK_MULTI_CLUSTER` environment variable, for example:
 
 ```bash
 $ COOK_MULTI_CLUSTER= nosetests tests.cook.test_multi_cook
 ```

To configure the second cook scheduler URL, set the `COOK_SCHEDULER_URL_2` environment variable. The default value is `http://localhost:22321`.

## Credits

This package was created with (Cookiecutter)[https://github.com/audreyr/cookiecutter] and the (audreyr/cookiecutter-pypackage)[https://github.com/audreyr/cookiecutter-pypackage] project template.
