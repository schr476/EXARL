# This material was prepared as an account of work sponsored by an agency of the
# United States Government.  Neither the United States Government nor the United
# States Department of Energy, nor Battelle, nor any of their employees, nor any
# jurisdiction or organization that has cooperated in the development of these
# materials, makes any warranty, express or implied, or assumes any legal
# liability or responsibility for the accuracy, completeness, or usefulness or
# any information, apparatus, product, software, or process disclosed, or
# represents that its use would not infringe privately owned rights. Reference
# herein to any specific commercial product, process, or service by trade name,
# trademark, manufacturer, or otherwise does not necessarily constitute or imply
# its endorsement, recommendation, or favoring by the United States Government
# or any agency thereof, or Battelle Memorial Institute. The views and opinions
# of authors expressed herein do not necessarily state or reflect those of the
# United States Government or any agency thereof.
#                 PACIFIC NORTHWEST NATIONAL LABORATORY
#                            operated by
#                             BATTELLE
#                             for the
#                   UNITED STATES DEPARTMENT OF ENERGY
#                    under Contract DE-AC05-76RL01830
import exarl.mpi_settings as mpi_settings
import time
import csv
from mpi4py import MPI
import numpy as np
import exarl as erl
from exarl.utils.profile import *
import exarl.utils.log as log
import exarl.utils.candleDriver as cd

logger = log.setup_logger(__name__, cd.run_params['log_level'])

class ML_RMA_V1(erl.ExaWorkflow):
    def __init__(self):
        print("Creating ML_RMA_V1 workflow")

    @PROFILE
    def run(self, workflow):
        # MPI communicators
        agent_comm = mpi_settings.agent_comm
        env_comm = mpi_settings.env_comm
        learner_comm = mpi_settings.learner_comm

        # Allocate RMA windows
        if mpi_settings.is_agent():

            # Get size of episode counter
            disp = MPI.DOUBLE.Get_size()
            episode_data = None
            if mpi_settings.is_learner() and learner_comm.rank == 0:
                episode_data = np.zeros(1, dtype=np.float64)
            # Create episode window (attach instead of allocate for zero initialization)
            episode_win = MPI.Win.Create(episode_data, disp, comm=agent_comm)

            # Get size of epsilon
            disp = MPI.DOUBLE.Get_size()
            epsilon = None
            if mpi_settings.is_learner() and learner_comm.rank == 0:
                epsilon = np.zeros(1, dtype=np.float64)
            # Create epsilon window
            epsilon_win = MPI.Win.Create(epsilon, disp, comm=agent_comm)

            # Get size of individual indices
            disp = MPI.INT.Get_size()
            indices = None
            if mpi_settings.is_learner() and learner_comm.rank == 0:
                indices = -1 * np.ones(workflow.agent.batch_size, dtype=np.intc)
            # Create indices window
            indices_win = MPI.Win.Create(indices, disp, comm=agent_comm)

            # Get size of loss
            disp = MPI.DOUBLE.Get_size()
            loss = None
            if mpi_settings.is_learner() and learner_comm.rank == 0:
                loss = np.zeros(workflow.agent.batch_size, dtype=np.float64)
            # Create epsilon window
            loss_win = MPI.Win.Create(loss, disp, comm=agent_comm)

            # Get serialized target weights size
            target_weights = workflow.agent.get_weights()
            serial_target_weights = MPI.pickle.dumps(target_weights)
            serial_target_weights_size = len(serial_target_weights)
            target_weights_size = 0
            if mpi_settings.is_learner() and learner_comm.rank == 0:
                target_weights_size = serial_target_weights_size
            # Allocate model window
            model_win = MPI.Win.Allocate(target_weights_size, 1, comm=agent_comm)

            # Get serialized batch data size
            agent_batch = next(workflow.agent.generate_data())
            serial_agent_batch = (MPI.pickle.dumps(agent_batch))
            serial_agent_batch_size = len(serial_agent_batch)
            nserial_agent_batch = 0
            if mpi_settings.is_actor():
                nserial_agent_batch = serial_agent_batch_size
            # Allocate data window
            data_win = MPI.Win.Allocate(nserial_agent_batch, 1, comm=agent_comm)

        if mpi_settings.is_learner() and learner_comm.rank == 0:
            # Write target weight to model window of learner
            model_win.Lock(0)
            model_win.Put(serial_target_weights, target_rank=0)
            model_win.Unlock(0)

        if mpi_settings.is_agent():
            # Synchronize
            agent_comm.Barrier()

        # Learner
        if mpi_settings.is_learner():
            # Initialize batch data buffer
            data_buffer = bytearray(serial_agent_batch_size)
            episode_count_learner = np.zeros(1, dtype=np.float64)
            epsilon = np.array(workflow.agent.epsilon, dtype=np.float64)
            # learner_counter = 0
            # Initialize epsilon
            debug = True
            get_time = 0.
            s_gtime = 0.
            lr_stime = MPI.Wtime()
            if learner_comm.rank == 0:

                # To check number of horovod train steps
                hvd_counter = 0
                train_time = 0.
                epsilon_win.Lock(0)
                epsilon_win.Put(epsilon, target_rank=0)
                epsilon_win.Flush(0)
                epsilon_win.Unlock(0)

            while episode_count_learner < workflow.nepisodes:
                # Define flags to keep track of data
                process_has_data = 0
                sum_process_has_data = 0

                if learner_comm.rank == 0:
                    # Check episode counter
                    episode_win.Lock(0)
                    # Atomic Get_accumulate to fetch episode count
                    episode_win.Get_accumulate(np.ones(1, dtype=np.float64), episode_count_learner, target_rank=0, op=MPI.NO_OP)
                    episode_win.Flush(0)
                    episode_win.Unlock(0)

                episode_count_learner = learner_comm.bcast(episode_count_learner, root=0)

                # Go over all actors (actor processes start from rank 1)
                # s = (learner_counter % (agent_comm.size - 1)) + 1
                # Randomly select actor
                # low = learner_comm.size  # start
                # high = agent_comm.size  # stop + 1
                # s = np.random.randint(low=low, high=high, size=1)

                s = rma_window_selector(debug)
                if debug:
                    debug = False

                # Get data
                # print(s)
                s_gtime = MPI.Wtime()
                data_win.Lock(s)
                data_win.Get(data_buffer, target_rank=s, target=None)
                data_win.Unlock(s)
                get_time += MPI.Wtime() - s_gtime

                # Check the data_buffer again if it is empty
                try:
                    agent_data = MPI.pickle.loads(data_buffer)
                    process_has_data = 1
                except:
                    logger.info('Data buffer is empty, continuing...')

                # Do an allreduce to check if all learners have data
                sum_process_has_data = learner_comm.allreduce(process_has_data, op=MPI.SUM)
                if (sum_process_has_data / learner_comm.size) < 1.0:
                    continue

                # Train & Target train
                # For debug purposes
                if learner_comm.rank == 0:
                    s_time = MPI.Wtime()
                train_return = workflow.agent.train(agent_data)

                if learner_comm.rank == 0:
                    hvd_counter += 1
                    train_time += MPI.Wtime() - s_time
                    # print("ML_RMA: Time taken to train (horovod) is {}. No of hvd trains = {}".format(MPI.Wtime()-s_time,hvd_counter))

                if train_return is not None:
                    if not np.array_equal(train_return[0], (-1 * np.ones(workflow.agent.batch_size))):
                        indices, loss = train_return
                        indices = np.array(indices, dtype=np.intc)
                        loss = np.array(loss, dtype=np.float64)

                if learner_comm.rank == 0:
                    # Write indices to memory pool
                    indices_win.Lock(0)
                    indices_win.Put(indices, target_rank=0)
                    indices_win.Unlock(0)

                    # Write losses to memory pool
                    loss_win.Lock(0)
                    loss_win.Put(loss, target_rank=0)
                    loss_win.Unlock(0)

                    # TODO: Double check if this is already in the DQN code
                    workflow.agent.target_train()
                    # Share new model weights
                    target_weights = workflow.agent.get_weights()
                    serial_target_weights = MPI.pickle.dumps(target_weights)
                    model_win.Lock(0)
                    model_win.Put(serial_target_weights, target_rank=0)
                    model_win.Unlock(0)
                # learner_counter += 1

            logger.info('Learner exit on rank_episode: {}_{}'.format(agent_comm.rank, episode_data))
            print("Learner {} : Total time: {}".format(learner_comm.rank, MPI.Wtime() - lr_stime))
            tmp = learner_comm.allreduce(get_time, op=MPI.SUM)
            if learner_comm.rank == 0:
                print("Learner 0 : Total time spent on training : {}".format(train_time))
                print("Learner 0 : Total horovod trainings done : {}".format(hvd_counter))
                print("Learner 0 : Training throughput : {} batches trained/sec".format((hvd_counter * learner_comm.size) / train_time))
                print("Learner 0: Average RMA Get Access time on all learners: {}".format(tmp / learner_comm.size))

            # print("Learner {} exited successfully!".format(learner_comm.rank))
            workflow.agent.learner_training_metrics()

        # Actors
        else:
            local_actor_episode_counter = 0
            episode_count_actor = 0
            if mpi_settings.is_actor():
                # Logging files
                filename_prefix = 'ExaLearner_' + 'Episodes%s_Steps%s_Rank%s_memory_v1' \
                    % (str(workflow.nepisodes), str(workflow.nsteps), str(agent_comm.rank))
                train_file = open(workflow.results_dir + '/' + filename_prefix + ".log", 'w')
                train_writer = csv.writer(train_file, delimiter=" ")

                put_counter = 0
                ac_stime = MPI.Wtime()
                episode_count_actor = np.zeros(1, dtype=np.float64)
                one = np.ones(1, dtype=np.float64)
                epsilon_update = np.zeros(1, dtype=np.float64)
                epsilon = np.zeros(1, dtype=np.float64)
                indices = -1 * np.ones(workflow.agent.batch_size, dtype=np.int32)
                loss = np.zeros(workflow.agent.batch_size, dtype=np.float64)

                # Get initial value of episode counter
                episode_win.Lock(0)
                # Atomic Get using Get_accumulate
                episode_win.Get_accumulate(one, episode_count_actor, target_rank=0, op=MPI.NO_OP)
                episode_win.Flush(0)
                episode_win.Unlock(0)

            episode_count_actor = env_comm.bcast(episode_count_actor, root=0)

            while episode_count_actor < workflow.nepisodes:
                if mpi_settings.is_actor():
                    episode_win.Lock(0)
                    # Atomic Get_accumulate to increment the episode counter
                    episode_win.Get_accumulate(one, episode_count_actor, target_rank=0)
                    episode_win.Flush(0)
                    episode_win.Unlock(0)

                episode_count_actor = env_comm.bcast(episode_count_actor, root=0)

                # Include another check to avoid each actor running extra
                # set of steps while terminating
                if episode_count_actor >= workflow.nepisodes:
                    break
                if mpi_settings.is_actor():
                    logger.info('Rank[{}] - working on episode: {}'.format(agent_comm.rank, episode_count_actor))

                # Episode initialization
                workflow.env.seed(0)
                current_state = workflow.env.reset()
                total_rewards = 0
                steps = 0
                action = 0
                done = False
                local_actor_episode_counter += 1

                while done != True:
                    if mpi_settings.is_actor():
                        # Update model weight
                        # TODO: weights are updated each step -- REVIEW --
                        buff = bytearray(serial_target_weights_size)
                        model_win.Lock(0)
                        model_win.Get(buff, target=0, target_rank=0)
                        model_win.Flush(0)
                        model_win.Unlock(0)
                        target_weights = MPI.pickle.loads(buff)
                        workflow.agent.set_weights(target_weights)

                        # Get epsilon
                        epsilon_win.Lock(0)
                        epsilon_win.Get(epsilon, target_rank=0)
                        epsilon_win.Flush(0)
                        epsilon_win.Unlock(0)

                        workflow.agent.epsilon = epsilon

                        # Get indices
                        indices_win.Lock(0)
                        indices_win.Get(indices, target_rank=0)
                        indices_win.Flush(0)
                        indices_win.Unlock(0)

                        # Get losses
                        loss_win.Lock(0)
                        loss_win.Get(loss, target_rank=0)
                        loss_win.Flush(0)
                        loss_win.Unlock(0)

                        if not np.array_equal(indices, (-1 * np.ones(workflow.agent.batch_size, dtype=np.intc))):
                            workflow.agent.set_priorities(indices, loss)

                        # Inference action
                        if workflow.action_type == 'fixed':
                            action, policy_type = 0, -11
                        else:
                            action, policy_type = workflow.agent.action(current_state)

                        epsilon = np.array(workflow.agent.epsilon)
                        # Atomic Get_accumulate to update epsilon
                        epsilon_win.Lock(0)
                        epsilon_win.Put(epsilon, target_rank=0)
                        epsilon_win.Flush(0)
                        epsilon_win.Unlock(0)

                    # Environment step
                    next_state, reward, done, _ = workflow.env.step(action)

                    steps += 1
                    if steps >= workflow.nsteps:
                        done = True
                    # Broadcast done
                    done = env_comm.bcast(done, root=0)

                    if mpi_settings.is_actor():
                        # Save memory
                        total_rewards += reward
                        memory = (current_state, action, reward, next_state, done, total_rewards)
                        workflow.agent.remember(memory[0], memory[1], memory[2], memory[3], memory[4])
                        batch_data = next(workflow.agent.generate_data())

                        # Write to data window
                        serial_agent_batch = (MPI.pickle.dumps(batch_data))
                        data_win.Lock(agent_comm.rank)
                        data_win.Put(serial_agent_batch, target_rank=agent_comm.rank)
                        data_win.Unlock(agent_comm.rank)
                        put_counter += 1
                        # print("Actor {} : RMA window put counter: {} ".format(agent_comm.rank,put_counter))

                        # Log state, action, reward, ...
                        train_writer.writerow([time.time(), current_state, action, reward, next_state, total_rewards,
                                               done, local_actor_episode_counter, steps, policy_type, workflow.agent.epsilon])
                        train_file.flush()

                    current_state = next_state

        if mpi_settings.is_actor():
            print("Actor {} : Total time: {} ".format(agent_comm.rank, MPI.Wtime() - ac_stime))
            print("Actor {} : RMA window put counter: {} ".format(agent_comm.rank, put_counter))

        if mpi_settings.is_agent():
            model_win.Free()
            data_win.Free()


def rma_window_selector(debug):
    # flag to selecting a actor's RMA window - set TRUE for random selection and FALSE for range based window selection
    random = False
    # random = True
    if random:
        low = mpi_settings.learner_comm.size  # start
        high = mpi_settings.agent_comm.size  # stop + 1
        s = np.random.randint(low=low, high=high)
    else:
        # distribute the actor windows uniformly across all the learners

        learner_procs = mpi_settings.learner_comm.size
        actor_procs = mpi_settings.agent_comm.size - learner_procs
        size = int(actor_procs / learner_procs)
        offset = actor_procs % learner_procs
        first_offset = size + offset

        if mpi_settings.learner_comm.rank == 0:
            low = learner_procs
            high = learner_procs + first_offset
        else:
            low = learner_procs + first_offset + ((mpi_settings.learner_comm.rank - 1) * size)
            high = learner_procs + first_offset + ((mpi_settings.learner_comm.rank) * size)

        s = np.random.randint(low=low, high=high)

        if debug:
            print("Random window selection policy is set to : {}".format(random))
            print("Learner {} Actor RMA windows allocated : {} ".format(mpi_settings.learner_comm.rank, range(low, high)))

    return s
