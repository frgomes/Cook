import logging
import time
import unittest
import uuid

from tests.cook import util


class CookTest(unittest.TestCase):
    _multiprocess_can_split_ = True

    @staticmethod
    def minimal_group(**kwargs):
        group = {"uuid": str(uuid.uuid4())}
        group.update(kwargs)
        return group

    def setUp(self):
        self.cook_url = util.retrieve_cook_url()
        self.logger = logging.getLogger(__name__)
        util.wait_for_cook(self.cook_url)

    def settings(self):
        return util.session.get('%s/settings' % self.cook_url).json()

    def get_job(self, job_uuid):
        """Loads a job by UUID using GET /rawscheduler"""
        return util.query_jobs(self.cook_url, job=[job_uuid]).json()[0]

    def test_basic_submit(self):
        job_uuid, resp = util.submit_job(self.cook_url)
        self.assertEqual(resp.status_code, 201)
        job = util.wait_for_job(self.cook_url, job_uuid, 'completed')
        self.assertEqual('success', job['instances'][0]['status'])
        self.assertEqual(False, job['disable_mea_culpa_retries'])

    def test_disable_mea_culpa(self):
        job_uuid, resp = util.submit_job(self.cook_url, disable_mea_culpa_retries=True)
        self.assertEqual(201, resp.status_code)
        job = self.get_job(job_uuid)
        self.assertEqual(True, job['disable_mea_culpa_retries'])

        job_uuid, resp = util.submit_job(self.cook_url, disable_mea_culpa_retries=False)
        self.assertEqual(201, resp.status_code)
        job = self.get_job(job_uuid)
        self.assertEqual(False, job['disable_mea_culpa_retries'])

    def test_failing_submit(self):
        job_uuid, resp = util.submit_job(self.cook_url, command='exit 1')
        self.assertEqual(201, resp.status_code)
        job = util.wait_for_job(self.cook_url, job_uuid, 'completed')
        self.assertEqual(1, len(job['instances']))
        self.assertEqual('failed', job['instances'][0]['status'])

    def test_max_runtime_exceeded(self):
        settings_timeout_interval_minutes = util.get_in(self.settings(), 'task-constraints', 'timeout-interval-minutes')
        # the value needs to be a little more than 2 times settings_timeout_interval_minutes to allow
        # at least two runs of the lingering task killer
        job_timeout_interval_seconds = (2 * settings_timeout_interval_minutes * 60) + 15
        job_uuid, resp = util.submit_job(self.cook_url, command='sleep %s' % job_timeout_interval_seconds, max_runtime=5000)
        self.assertEqual(201, resp.status_code)
        job = util.wait_for_job(self.cook_url, job_uuid, 'completed', job_timeout_interval_seconds * 1000)
        self.assertEqual(1, len(job['instances']))
        self.assertEqual('failed', job['instances'][0]['status'])
        self.assertEqual(2003, job['instances'][0]['reason_code'])


    def test_get_job(self):
        # schedule a job
        job_spec = util.minimal_job()
        resp = util.session.post('%s/rawscheduler' % self.cook_url, json={'jobs': [job_spec]})
        self.assertEqual(201, resp.status_code)

        # query for the same job & ensure the response has what it's supposed to have
        job = util.wait_for_job(self.cook_url, job_spec['uuid'], 'completed')
        self.assertEquals(job_spec['mem'], job['mem'])
        self.assertEquals(job_spec['max_retries'], job['max_retries'])
        self.assertEquals(job_spec['name'], job['name'])
        self.assertEquals(job_spec['priority'], job['priority'])
        self.assertEquals(job_spec['uuid'], job['uuid'])
        self.assertEquals(job_spec['cpus'], job['cpus'])
        self.assertTrue('labels' in job)
        self.assertEquals(9223372036854775807, job['max_runtime'])
        # 9223372036854775807 is MAX_LONG(ish), the default value for max_runtime
        self.assertEquals('success', job['state'])
        self.assertTrue('env' in job)
        self.assertTrue('framework_id' in job)
        self.assertTrue('ports' in job)
        self.assertTrue('instances' in job)
        self.assertEquals('completed', job['status'])
        self.assertTrue(isinstance(job['submit_time'], int))
        self.assertTrue('uris' in job)
        self.assertTrue('retries_remaining' in job)
        instance = job['instances'][0]
        self.assertTrue(isinstance(instance['start_time'], int))
        self.assertTrue('executor_id' in instance)
        self.assertTrue('hostname' in instance)
        self.assertTrue('slave_id' in instance)
        self.assertTrue(isinstance(instance['preempted'], bool))
        self.assertTrue(isinstance(instance['end_time'], int))
        self.assertTrue(isinstance(instance['backfilled'], bool))
        self.assertTrue('ports' in instance)
        self.assertEquals('completed', job['status'])
        self.assertTrue('task_id' in instance)

    def determine_user(self):
        job_spec = util.minimal_job()
        request_body = {'jobs': [job_spec]}
        resp = util.session.post('%s/rawscheduler' % self.cook_url, json=request_body)
        self.assertEqual(resp.status_code, 201)
        return self.get_job(job_spec['uuid'])['user']

    def test_list_jobs_by_state(self):
        # schedule a bunch of jobs in hopes of getting jobs into different statuses
        request_body = {'jobs': [util.minimal_job(command="sleep %s" % i) for i in range(1, 20)]}
        resp = util.session.post('%s/rawscheduler' % self.cook_url, json=request_body)
        self.assertEqual(resp.status_code, 201)

        # let some jobs get scheduled
        time.sleep(10)
        user = self.determine_user()

        for state in ['waiting', 'running', 'completed']:
            resp = util.session.get('%s/list?user=%s&state=%s' % (self.cook_url, user, state))
            self.assertEqual(200, resp.status_code)
            jobs = resp.json()
            for job in jobs:
                # print "%s %s" % (job['uuid'], job['status'])
                self.assertEquals(state, job['status'])

    def test_list_jobs_by_time(self):
        # schedule two jobs with different submit times
        job_specs = [util.minimal_job() for _ in range(2)]

        request_body = {'jobs': [job_specs[0]]}
        resp = util.session.post('%s/rawscheduler' % self.cook_url, json=request_body)
        self.assertEqual(resp.status_code, 201)

        time.sleep(1)

        request_body = {'jobs': [job_specs[1]]}
        resp = util.session.post('%s/rawscheduler' % self.cook_url, json=request_body)
        self.assertEqual(resp.status_code, 201)

        submit_times = [self.get_job(job_spec['uuid'])['submit_time'] for job_spec in job_specs]

        user = self.determine_user()

        # start-ms and end-ms are exclusive

        # query where start-ms and end-ms are the submit times of jobs 1 & 2 respectively
        resp = util.session.get('%s/list?user=%s&state=waiting&start-ms=%s&end-ms=%s'
                                % (self.cook_url, user, submit_times[0] - 1, submit_times[1] + 1))
        self.assertEqual(200, resp.status_code)
        jobs = resp.json()
        self.assertTrue(any(job for job in jobs if job['uuid'] == job_specs[0]['uuid']))
        self.assertTrue(any(job for job in jobs if job['uuid'] == job_specs[1]['uuid']))

        # query just for job 1
        resp = util.session.get('%s/list?user=%s&state=waiting&start-ms=%s&end-ms=%s'
                                % (self.cook_url, user, submit_times[0] - 1, submit_times[1]))
        self.assertEqual(200, resp.status_code)
        jobs = resp.json()
        self.assertTrue(any(job for job in jobs if job['uuid'] == job_specs[0]['uuid']))
        self.assertFalse(any(job for job in jobs if job['uuid'] == job_specs[1]['uuid']))

        # query just for job 2
        resp = util.session.get('%s/list?user=%s&state=waiting&start-ms=%s&end-ms=%s'
                                % (self.cook_url, user, submit_times[0], submit_times[1] + 1))
        self.assertEqual(200, resp.status_code)
        jobs = resp.json()
        self.assertFalse(any(job for job in jobs if job['uuid'] == job_specs[0]['uuid']))
        self.assertTrue(any(job for job in jobs if job['uuid'] == job_specs[1]['uuid']))

        # query for neither
        resp = util.session.get('%s/list?user=%s&state=waiting&start-ms=%s&end-ms=%s'
                                % (self.cook_url, user, submit_times[0], submit_times[1]))
        self.assertEqual(200, resp.status_code)
        jobs = resp.json()
        self.assertFalse(any(job for job in jobs if job['uuid'] == job_specs[0]['uuid']))
        self.assertFalse(any(job for job in jobs if job['uuid'] == job_specs[1]['uuid']))

    def test_cancel_job(self):
        job_uuid, _ = util.submit_job(self.cook_url, command='sleep 300')
        util.wait_for_job(self.cook_url, job_uuid, 'running')
        resp = util.session.delete('%s/rawscheduler?job=%s' % (self.cook_url, job_uuid))
        self.assertEqual(204, resp.status_code)
        job = util.session.get('%s/rawscheduler?job=%s' % (self.cook_url, job_uuid)).json()[0]
        self.assertEqual('failed', job['state'])

    def test_change_retries(self):
        job_uuid, _ = util.submit_job(self.cook_url, command='sleep 10')
        util.wait_for_job(self.cook_url, job_uuid, 'running')
        resp = util.session.delete('%s/rawscheduler?job=%s' % (self.cook_url, job_uuid))
        self.assertEqual(204, resp.status_code)
        job = util.session.get('%s/rawscheduler?job=%s' % (self.cook_url, job_uuid)).json()[0]
        self.assertEqual('failed', job['state'])
        resp = util.session.put('%s/retry' % self.cook_url, json={'retries': 2, 'jobs': [job_uuid]})
        self.assertEqual(201, resp.status_code, resp.text)
        job = util.session.get('%s/rawscheduler?job=%s' % (self.cook_url, job_uuid)).json()[0]
        self.assertEqual('waiting', job['status'])
        job = util.wait_for_job(self.cook_url, job_uuid, 'completed')
        self.assertEqual('success', job['state'])

    def test_cancel_instance(self):
        job_uuid, _ = util.submit_job(self.cook_url, command='sleep 10', max_retries=2)
        job = util.wait_for_job(self.cook_url, job_uuid, 'running')
        task_id = job['instances'][0]['task_id']
        resp = util.session.delete('%s/rawscheduler?instance=%s' % (self.cook_url, task_id))
        self.assertEqual(204, resp.status_code)
        job = util.wait_for_job(self.cook_url, job_uuid, 'completed')
        self.assertEqual('success', job['state'])

    def test_implicit_group(self):
        group_uuid = str(uuid.uuid4())
        job_a = util.minimal_job(group=group_uuid)
        job_b = util.minimal_job(group=group_uuid)
        data = {'jobs': [job_a, job_b]}
        resp = util.session.post('%s/rawscheduler' % self.cook_url, json=data)
        self.assertEqual(resp.status_code, 201)
        jobs = util.session.get('%s/rawscheduler?job=%s&job=%s' %
                                (self.cook_url, job_a['uuid'], job_b['uuid']))
        self.assertEqual(200, jobs.status_code)
        jobs = jobs.json()
        self.assertEqual(group_uuid, jobs[0]['groups'][0])
        self.assertEqual(group_uuid, jobs[1]['groups'][0])
        util.wait_for_job(self.cook_url, job_a['uuid'], 'completed')
        util.wait_for_job(self.cook_url, job_b['uuid'], 'completed')

    def test_explicit_group(self):
        group_spec = self.minimal_group()
        job_a = util.minimal_job(group=group_spec["uuid"])
        job_b = util.minimal_job(group=group_spec["uuid"])
        data = {'jobs': [job_a, job_b], 'groups': [group_spec]}
        resp = util.session.post('%s/rawscheduler' % self.cook_url, json=data)
        self.assertEqual(resp.status_code, 201)
        jobs = util.session.get('%s/rawscheduler?job=%s&job=%s' %
                                (self.cook_url, job_a['uuid'], job_b['uuid']))
        self.assertEqual(200, jobs.status_code)
        jobs = jobs.json()
        self.assertEqual(group_spec['uuid'], jobs[0]['groups'][0])
        self.assertEqual(group_spec['uuid'], jobs[1]['groups'][0])
        util.wait_for_job(self.cook_url, job_a['uuid'], 'completed')
        util.wait_for_job(self.cook_url, job_b['uuid'], 'completed')

    def test_straggler_handling(self):
        straggler_handling = {
            'type': 'quantile-deviation',
            'parameters': {
                'quantile': 0.5,
                'multiplier': 2.0
            }
        }
        group_spec = self.minimal_group(straggler_handling=straggler_handling)
        job_fast = util.minimal_job(group=group_spec["uuid"])
        job_slow = util.minimal_job(group=group_spec["uuid"], command='sleep 120')
        data = {'jobs': [job_fast, job_slow], 'groups': [group_spec]}
        resp = util.session.post('%s/rawscheduler' % self.cook_url, json=data)
        self.assertEqual(resp.status_code, 201)
        util.wait_for_job(self.cook_url, job_fast['uuid'], 'completed')
        util.wait_for_job(self.cook_url, job_slow['uuid'], 'completed')
        jobs = util.session.get('%s/rawscheduler?job=%s&job=%s' %
                                (self.cook_url, job_fast['uuid'], job_slow['uuid']))
        self.assertEqual(200, jobs.status_code)
        jobs = jobs.json()
        self.logger.debug('Loaded jobs %s', jobs)
        self.assertEqual('success', jobs[0]['state'])
        self.assertEqual('failed', jobs[1]['state'])
        self.assertEqual(2004, jobs[1]['instances'][0]['reason_code'])

    def test_expected_runtime_field(self):
        # Should support expected_runtime
        expected_runtime = 1
        job_uuid, resp = util.submit_job(self.cook_url, expected_runtime=expected_runtime)
        self.assertEqual(resp.status_code, 201)
        job = util.wait_for_job(self.cook_url, job_uuid, 'completed')
        self.assertEqual('success', job['instances'][0]['status'])
        self.assertEqual(expected_runtime, job['expected_runtime'])

        # Should disallow expected_runtime > max_runtime
        expected_runtime = 2
        max_runtime = expected_runtime - 1
        job_uuid, resp = util.submit_job(self.cook_url, expected_runtime=expected_runtime, max_runtime=max_runtime)
        self.assertEqual(resp.status_code, 400)

    def test_application_field(self):
        # Should support application
        application = {'name': 'foo-app', 'version': '0.1.0'}
        job_uuid, resp = util.submit_job(self.cook_url, application=application)
        self.assertEqual(resp.status_code, 201)
        job = util.wait_for_job(self.cook_url, job_uuid, 'completed')
        self.assertEqual('success', job['instances'][0]['status'])
        self.assertEqual(application, job['application'])

        # Should require application name
        _, resp = util.submit_job(self.cook_url, application={'version': '0.1.0'})
        self.assertEqual(resp.status_code, 400)

        # Should require application version
        _, resp = util.submit_job(self.cook_url, application={'name': 'foo-app'})
        self.assertEqual(resp.status_code, 400)

    def test_error_while_creating_job(self):
        job1 = util.minimal_job()
        job2 = util.minimal_job(uuid=job1['uuid'])
        resp = util.session.post('%s/rawscheduler' % self.cook_url,
                                 json={'jobs':[job1, job2]})
        self.assertEqual(resp.status_code, 500)

    def test_allow_partial(self):
        def absent_uuids(response):
            return [part for part in response.json()['error'].split() if util.is_valid_uuid(part)]

        job_uuid_1, resp = util.submit_job(self.cook_url)
        self.assertEqual(201, resp.status_code)
        job_uuid_2, resp = util.submit_job(self.cook_url)
        self.assertEqual(201, resp.status_code)

        # Only valid job uuids
        resp = util.query_jobs(self.cook_url, job=[job_uuid_1, job_uuid_2])
        self.assertEqual(200, resp.status_code)

        # Mixed valid, invalid job uuids
        bogus_uuid = str(uuid.uuid4())
        resp = util.query_jobs(self.cook_url, job=[job_uuid_1, job_uuid_2, bogus_uuid])
        self.assertEqual(404, resp.status_code)
        self.assertEqual([bogus_uuid], absent_uuids(resp))
        resp = util.query_jobs(self.cook_url, job=[job_uuid_1, job_uuid_2, bogus_uuid], partial='false')
        self.assertEqual(404, resp.status_code, resp.json())
        self.assertEqual([bogus_uuid], absent_uuids(resp))

        # Partial results with mixed valid, invalid job uuids
        resp = util.query_jobs(self.cook_url, job=[job_uuid_1, job_uuid_2, bogus_uuid], partial='true')
        self.assertEqual(200, resp.status_code, resp.json())
        self.assertEqual(2, len(resp.json()))
        self.assertEqual([job_uuid_1, job_uuid_2].sort(), [job['uuid'] for job in resp.json()].sort())

        # Only valid instance uuids
        job = util.wait_for_job(self.cook_url, job_uuid_1, 'completed')
        instance_uuid_1 = job['instances'][0]['task_id']
        job = util.wait_for_job(self.cook_url, job_uuid_2, 'completed')
        instance_uuid_2 = job['instances'][0]['task_id']
        resp = util.query_jobs(self.cook_url, instance=[instance_uuid_1, instance_uuid_2])
        self.assertEqual(200, resp.status_code)

        # Mixed valid, invalid instance uuids
        resp = util.query_jobs(self.cook_url, instance=[instance_uuid_1, instance_uuid_2, bogus_uuid])
        self.assertEqual(404, resp.status_code)
        self.assertEqual([bogus_uuid], absent_uuids(resp))
        resp = util.query_jobs(self.cook_url, instance=[instance_uuid_1, instance_uuid_2, bogus_uuid], partial='false')
        self.assertEqual(404, resp.status_code)
        self.assertEqual([bogus_uuid], absent_uuids(resp))

        # Partial results with mixed valid, invalid instance uuids
        resp = util.query_jobs(self.cook_url, instance=[instance_uuid_1, instance_uuid_2, bogus_uuid], partial='true')
        self.assertEqual(200, resp.status_code)
        self.assertEqual(2, len(resp.json()))
        self.assertEqual([job_uuid_1, job_uuid_2].sort(), [job['uuid'] for job in resp.json()].sort())
