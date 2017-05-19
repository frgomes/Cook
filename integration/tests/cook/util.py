import logging
import uuid

import importlib
import os

import requests
from functools import reduce
from retrying import retry

logger = logging.getLogger(__name__)
session = importlib.import_module(os.getenv('COOK_SESSION_MODULE', 'requests')).Session()


def get_in(dct, *keys):
    for key in keys:
        try:
            dct = dct[key]
        except KeyError:
            return None
    return dct


def dict_as_string(dct):
    def value_to_string(value):
        if not value:
            return str(value)
        elif isinstance(value, str):
            return repr(value)
        elif isinstance(value, dict):
            return dict_as_string(value)
        elif isinstance(value, list):
            return reduce(lambda acc, item: acc + value_to_string(item) + ', ', value, '[')[:-2] + ']'
        else:
            return str(value)
    if dct and isinstance(dct, dict):
        return reduce(lambda acc, item: acc + value_to_string(item[0]) + ': ' + value_to_string(item[1]) + ', ',
                      sorted(dct.items()),
                      '{')[:-2] + '}'
    elif not dct:
        return str(dct)
    else:
        return str(dct) + ' [type=' + str(type(dct)) + ']'


def is_valid_uuid(uuid_to_test, version=4):
    """
    Check if uuid_to_test is a valid UUID.
    Parameters
    ----------
    uuid_to_test : str
    version : {1, 2, 3, 4}
    Returns
    -------
    `True` if uuid_to_test is a valid UUID, otherwise `False`.
    Examples
    --------
    >>> is_valid_uuid('c9bf9e57-1685-4c89-bafb-ff5af830be8a')
    True
    >>> is_valid_uuid('c9bf9e58')
    False
    """
    try:
        uuid_obj = uuid.UUID(uuid_to_test, version=version)
    except:
        return False

    return str(uuid_obj) == uuid_to_test


def retrieve_cook_url(varname='COOK_SCHEDULER_URL', value='http://localhost:12321'):
    cook_url = os.getenv(varname, value)
    logger.info('Using cook url %s' % cook_url)
    return cook_url


def is_connection_error(exception):
    return isinstance(exception, requests.exceptions.ConnectionError)


@retry(retry_on_exception=is_connection_error, stop_max_delay=240000, wait_fixed=1000)
def wait_for_cook(cook_url):
    logger.debug('Waiting for connection to cook...')
    # if connection is refused, an exception will be thrown
    session.get(cook_url)


def minimal_job(**kwargs):
    job = {
        'command': 'echo hello',
        'cpus': 1,
        'max_retries': 1,
        'mem': 256,
        'name': 'echo',
        'priority': 1,
        'uuid': str(uuid.uuid4())
    }
    job.update(kwargs)
    return job


def submit_job(cook_url, **kwargs):
    job_spec = minimal_job(**kwargs)
    request_body = {'jobs': [job_spec]}
    resp = session.post('%s/rawscheduler' % cook_url, json=request_body)
    return job_spec['uuid'], resp


def load_job(cook_url, job_id):
    response = session.get('%s/rawscheduler?job=%s' % (cook_url, job_id))
    return response.json()[0]


def wait_for_job(cook_url, job_id, status, max_delay=120000):
    @retry(stop_max_delay=max_delay, wait_fixed=1000)
    def wait_for_job_inner():
        response = session.get('%s/rawscheduler?job=%s' % (cook_url, job_id))
        assert 200 == response.status_code
        job = response.json()[0]
        if not job['status'] == status:
            error_msg = 'Job %s had status %s - expected %s. Details: %s'.format(
                job_id, job['status'], status, dict_as_string(job))
            logger.info(error_msg)
            raise RuntimeError(error_msg)
        else:
            logger.info('Job %s has status %s', job_id, status)
            return job

    return wait_for_job_inner()


def query_jobs(cook_url, **kwargs):
    """
    Queries cook for a set of jobs, by job and/or instance uuid. The kwargs
    passed to this function are sent straight through as query parameters on
    the request.
    """
    return session.get('%s/rawscheduler' % cook_url, params=kwargs)
