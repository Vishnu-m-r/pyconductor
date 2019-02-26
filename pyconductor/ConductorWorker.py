#
#  Copyright 2017 Netflix, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
from __future__ import print_function, absolute_import
import sys
import time
from pyconductor.conductor import WFClientMgr
from threading import Thread
import socket

hostname = socket.gethostname()


class ConductorWorker:
    """
    Main class for implementing Conductor Workers

    A conductor worker is a separate system that executes the various
    tasks that the conductor server queues up for execution. The worker
    can run on the same instance as the server or on a remote instance.

    The worker generally provides a wrapper around some function that
    performs the actual execution of the task. The function that is
    being executed must return a `dict` with the `status`, `output` and
    `log` keys. If these keys are not present, the worker will raise an
    Exception after completion of the task.
    """
    def __init__(self, server_url, thread_count=1, polling_interval=1, worker_id=None):
        wfcMgr = WFClientMgr(server_url)
        self.workflowClient = wfcMgr.workflowClient
        self.taskClient = wfcMgr.taskClient
        # Checking that the arguments are valid. Converting thread_count
        # to float as that is a little more lenient. It will be converted
        # to int when it is being used.
        self.thread_count = float(thread_count)
        self.polling_interval = float(polling_interval)
        self.worker_id = worker_id or hostname

    def execute(self, task, exec_function):
        try:
            resp = exec_function(task)
            if type(resp) is not dict or not all(key in resp for key in ('status', 'output', 'logs')):
                raise Exception('Task execution function MUST return a response as a dict with status, output and logs fields')
            task['status'] = resp['status']
            task['outputData'] = resp['output']
            task['logs'] = resp['logs']
            self.taskClient.updateTask(task)
        except Exception as err:
            print('Error executing task: ' + str(err))
            task['status'] = 'FAILED'
            self.taskClient.updateTask(task)

    def poll_and_execute(self, taskType, exec_function, domain=None):
        while True:
            time.sleep(float(self.polling_interval))
            polled = self.taskClient.pollForTask(taskType, self.worker_id, domain)
            if polled is not None:
                if self.taskClient.ackTask(polled['taskId'], self.worker_id):
                    self.execute(polled, exec_function)

    def start(self, taskType, exec_function, wait, domain=None):
        print('Polling for task %s at a %f ms interval with %d threads for task execution, with worker id as %s' % (taskType, self.polling_interval * 1000, self.thread_count, self.worker_id))
        for x in range(0, int(self.thread_count)):
            thread = Thread(target=self.poll_and_execute, args=(taskType, exec_function, domain,))
            thread.daemon = True
            thread.start()
        if wait:
            while 1:
                time.sleep(1)

    def consume(self, taskType, exec_function, domain=None, limit=0, check_existing_tasks=True):
        """
        If we don't want to set up a continously polling worker,
        then we might want to use consume. It checks if the task
        is available. If available, it spawns threads to complete
        the task. If not, it ends. This allows different usage
        patterns, like ensuring that one system is only processing
        one task at a time. Using this also allows for easy updates
        to the worker code.

        limit and check_existing_tasks are not yet supported
        """
        while True:
            polled = self.taskClient.pollForTask(taskType, self.worker_id, domain)
            if polled is None:
                break
            if self.taskClient.ackTask(polled['taskId'], self.worker_id):
                thread = Thread(target=self.execute, args=(polled, exec_function,))
                thread.start()


def exc(taskType, inputData, startTime, retryCount, status, callbackAfterSeconds, pollCount):
    print('Executing the function')
    return {'status': 'COMPLETED', 'output': {}}


def main():
    cc = ConductorWorker('http://localhost:8080/api', 5, 0.1)
    cc.start(sys.argv[1], exc, False)
    cc.start(sys.argv[2], exc, True)


if __name__ == '__main__':
    main()
