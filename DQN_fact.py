import factory_sim2 as fact_sim
import numpy as np
import pandas as pd
import math 
import matplotlib
import random
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from itertools import chain
import DeepQNet

sim_time = 1e5
WEEK = 24*7
NO_OF_WEEKS = math.ceil(sim_time/WEEK)
num_seq_steps = 20

recipes = pd.read_csv('~/Documents/workspace/WDsim/recipes.csv')
machines = pd.read_csv('~/Documents/workspace/WDsim/machines.csv')

recipes = recipes[recipes.MAXIMUMLS != 0]

# Create the machine dictionary (machine:station)
machine_d = dict()
for index, row in machines.iterrows():
    d = {row[0]:row[1]}
    machine_d.update(d)

# Modifying the above list to match the stations from the two datasets
a = machines.TOOLSET.unique()
b = recipes.TOOLSET.unique()
common_stations = (set(a) & set(b))
ls = list(common_stations)

# This dictionary has the correct set of stations
modified_machine_dict = {k: v for k, v in machine_d.items() if v in ls}

# Removing unncommon rows from recipes 
for index, row in recipes.iterrows():
    if row[2] not in ls:
        recipes.drop(index, inplace=True)

recipes = recipes.dropna()
recipe_dict = dict()
for ht in list(recipes.HT.unique()):
    temp = recipes.loc[recipes['HT'] == ht]
    if len(temp) > 1:
        ls = []
        for index, row in temp.iterrows():
            ls.append([row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9]])
        d  = {ht:ls}
        recipe_dict.update(d)
    else:
        ls = []
        ls.append([row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9]])
        d = {ht:ls}
        recipe_dict.update(d)

# take only the first num_seq_steps sequence steps for each recipe to reduce the complexity of the simulation.
for ht, step in recipe_dict.items():
    recipe_dict[ht] = step[0:num_seq_steps]

# Dictionary where the key is the name of the machine and the value is [station, proc_t]
# machine_dict = {'m0': 's1', 'm2': 's2', 'm1': 's1', 'm3': 's2'}
machine_dict = modified_machine_dict

# recipes give the sequence of stations that must be processed at for the wafer of that head type to be completed
# recipes = {"ht1": [["s1", 5, 0]], "ht2": [["s1", 5, 0], ["s2", 5, 0]]}
recipes = recipe_dict

wafers_per_box = 4

break_mean = 1e5

repair_mean = 20

n_part_mix = 30

# average lead time for each head type
head_types = recipes.keys()
lead_dict = {}

part_mix = {}


for ht in head_types:
    d = {ht:15000}
    lead_dict.update(d)

    w = {ht:1}
    part_mix.update(w)


####################################################
########## CREATING THE STATE SPACE  ###############
####################################################
def get_state(sim):
    # Calculate the state space representation.
    # This returns a list containing the number of` parts in the factory for each combination of head type and sequence
    # step
    # state_rep = [len([wafer for queue in sim.queue_lists.values() for wafer in queue if wafer.HT
    #              == ht and wafer.seq == s]) for ht in list(sim.recipes.keys()) for s in
    #              list(range(len(sim.recipes[ht])))]

    state_rep = sum([sim.n_HT_seq[HT] for HT in sim.recipes.keys()], [])

    # assert state_rep == state_rep2
    print(len(state_rep))
    # b is a one-hot encoded list indicating which machine the next action will correspond to
    b = np.zeros(len(sim.machines_list))
    print(len(b))
    b[sim.machines_list.index(sim.next_machine)] = 1
    state_rep.extend(b)
    # Append the due dates list to the state space for making the decision
    rolling_window = [] # This is the rolling window that will be appended to state space
    max_length_of_window = math.ceil(max(sim.lead_dict.values()) / (7*24*60)) # Max length of the window to roll
    print(max_length_of_window)
    current_time = sim.env.now # Calculating the current time
    current_week = math.ceil(current_time / (7*24*60)) #Calculating the current week 

    for key, value in sim.due_wafers.items():
        rolling_window.append(value[current_week:current_week+max_length_of_window]) #Adding only the values from current week up till the window length
        buffer_list = [] # This list stores value of previous unfinished wafers count
        buffer_list.append(sum(value[:current_week]))
        rolling_window.extend([buffer_list])

    c = sum(rolling_window, [])
    state_rep.extend(c) # Appending the rolling window to state space
    print(len(state_rep))
    return state_rep


# Create the factory simulation object
my_sim = fact_sim.FactorySim(sim_time, machine_dict, recipes, lead_dict, wafers_per_box, part_mix, n_part_mix)
# start the simulation
my_sim.start()
# Retrieve machine object for first action choice
mach = my_sim.next_machine
# Save the state and allowed actions at the start for later use in training examples
state = get_state(my_sim)
allowed_actions = my_sim.allowed_actions
# The action space is a list of tuples of the form [('ht1',0), ('ht1',1), ..., ('ht2', 0), ...] indicating the head
# types and sequence steps for all allowed actions.
action_space = list(chain.from_iterable(my_sim.station_HT_seq.values()))
action_size = len(action_space)
state_size = len(state)

# Creating the DQN agent
dqn_agent = DeepQNet.DQN(state_space_dim= state_size, action_space= action_space, epsilon_decay=0.9999)

order_count = 0

while my_sim.env.now < sim_time:
    action = dqn_agent.choose_action(state, allowed_actions)

    wafer_choice = next(wafer for wafer in my_sim.queue_lists[mach.station] if wafer.HT == action[0] and wafer.seq ==
                        action[1])

    my_sim.run_action(mach, wafer_choice)
    print('Step Reward:' + str(my_sim.step_reward))
    # Record the machine, state, allowed actions and reward at the new time step
    next_mach = my_sim.next_machine
    next_state = get_state(my_sim)
    next_allowed_actions = my_sim.allowed_actions
    reward = my_sim.step_reward

    print(f"state dimension: {len(state)}")
    print(f"next state dimension: {len(next_state)}")
    print("action space dimension:", action_size)
    # record the information for use again in the next training example
    mach, allowed_actions, state = next_mach, next_allowed_actions, next_state
    print("State:", state)

    # Save the example for later training
    dqn_agent.remember(state, action, reward, next_state, next_allowed_actions)

    if my_sim.order_completed:
        # After each wafer completed, train the policy network 
        dqn_agent.replay()
        order_count+= 1
        if order_count >= 1:
            # After every 20 processes update the target network and reset the order count
            dqn_agent.train_target()
            order_count = 0

    # Record the information for use again in the next training example
    mach, allowed_actions, state = next_mach, next_allowed_actions, next_state


# Save the trained DQN policy network
dqn_agent.save_model("DQN_model_5e5.h5")

# Total wafers produced
print("Total wafers produced:", len(my_sim.cycle_time))


#Wafers of each head type
print("### Wafers of each head type ###")
print("### Wafers of each head type ###")

print(my_sim.lateness)

print(my_sim.complete_wafer_dict)

print(np.mean(my_sim.lateness[-1000:]))

print(dqn_agent.epsilon)

# Plot the time taken to complete each wafer
plt.plot(my_sim.lateness)
plt.xlabel("Wafers")
plt.ylabel("lateness")
plt.title("The amount of time each wafer was late")
plt.show()









