import json
import requests
from retrying import retry
import time
import unittest
import uuid

class CookTest(unittest.TestCase):

    @retry(stop_max_delay=120000, wait_fixed=5000)
    def wait_for_job(self, job_id, status):
        job = self.session.get('%s/rawscheduler?job=%s' % (self.cook_url, job_id))
        self.assertEqual(200, job.status_code)
        job = job.json()[0]
        self.assertEqual(status, job['status'])
        return job

    def minimal_job(self, uuid):
        return {
            'max_retries': 1,
            'mem': 100,
            'cpus': 1,
            'uuid': str(uuid),
            'command': 'echo hello',
            'name': 'echo',
            'priority': 1
        }


    def setUp(self):
        self.cook_url = 'http://localhost:12321'
        self.session = requests.Session()

    def test_basic_submit(self):
        job_uuid = uuid.uuid4()
        request_body = {'jobs': [ self.minimal_job(job_uuid) ]}
        resp = self.session.post('%s/rawscheduler' % self.cook_url, json=request_body)
        self.assertEqual(resp.status_code, 201)
        job = self.wait_for_job(job_uuid, 'completed')
        self.assertEquals('success', job['instances'][0]['status'])

    def test_failing_submit(self):
        job_uuid = uuid.uuid4()
        jobspec = self.minimal_job(job_uuid)
        jobspec['command'] = 'exit 1'
        resp = self.session.post('%s/rawscheduler' % self.cook_url,
                                 json={'jobs': [jobspec]})
        self.assertEquals(201, resp.status_code)
        job = self.wait_for_job(job_uuid, 'completed')
        self.assertEquals(1, len(job['instances']))
        self.assertEquals('failed', job['instances'][0]['status'])
