import pandas as pd
import numpy as np
import math, sys

def read_data(filename):

        frame = pd.read_csv(filename, sep=' ',
                            header=None,
                            names=['time', 'current_state', 'action', 'reward', 'next_state', 'total_reward', 'done',
                                   'episode', 'step', 'policy_type', 'epsilon'])

        ## Make time relative to the start time ##
        frame['time'] = pd.to_datetime(frame['time'], unit='ns')
        frame = frame[frame.done == True]
        return frame

    data = pd.read_csv(filename, header=None, delim_whitespace=True)
    return data 

## Can all log files
df_ranks = []
for filename in os.listdir(RESULTS_DIR):
    if filename.endswith(".log"):
        print('filename:{}'.format(filename))
        df = read_data(RESULTS_DIR + filename)
        df_ranks.append(df)
        print(df.head())

# df_merged = reduce(lambda  left,right: pd.merge(left,right,on=['time'],how='outer'), df_ranks)
df_merged = pd.concat(df_ranks)
df_merged.set_index('episode', inplace=True)
df_merged = df_merged.reset_index()
fig,ax = plt.subplots(figsize=(14,12))
ax.plot(df_merged['total_reward'], label='Total Reward', color='blue')
plt.xlabel('Episodes')
plt.ylabel('Total Reward')

import os, pandas
import matplotlib.pyplot as plt
USER = os.getenv('USER')
results_dir = '/gpfs/alpine/ast153/scratch/' + USER
ana_dir = 'TDLG/EXP000/RUN_'
dir_name = '16nodes_96procs'
results_dir += ana_dir+dir_name
if not os.path.exists(results_dir+'/Plots'):
    os.makedirs(results_dir+'/Plots')

window = 1
stop = 100
fig = plt.figure(figsize=(12, 9))  
plot = None
data_sum = pd.DataFrame()
nfiles=0
for filename in os.listdir(results_dir):
    if filename.endswith(".log"): 
        pfn = os.path.join(results_dir, filename)
        data0 = read_data(pfn)
        fdata0 = (data0[data0[5]==True]).reset_index(drop=True) 
        if data_sum.size==0:
            data_sum = fdata0
        else:
            data_sum = data_sum.add(fdata0)#, fill_value=0)  

        fdata0['sliding'] = fdata0.iloc[:,4].rolling(window).mean()
        plot = fdata0['sliding'][window:stop].plot(label=filename,legend=True)

        nfiles+=1
        continue
    else:
        continue
                           
plt.xlabel('Episode', fontsize = 15, weight = 'bold')
plt.ylabel('Total Episode Reward', fontsize = 15, weight = 'bold')
plt.legend(bbox_to_anchor=(1.04,1),fontsize = 15, loc="upper left")
plt.xlim((0, 100))
fig.savefig(results_dir+'/Plots/Individual_result_%s.png' % dir_name)

data_sum[4]=data_sum[4]/float(nfiles)
fig = plt.figure(figsize=(12, 9))
data_sum[4].plot(label='Average reward over all ranks',legend=True)
plt.xlabel('Episode', fontsize = 15, weight = 'bold')
plt.ylabel('Total Episode Reward (max=100)', fontsize = 15, weight = 'bold')
plt.title('ExaRL single learner DQN+CartPole (np=%s)'%str(nfiles), fontsize = 15, weight = 'bold')
plt.xlim((0, 100))                                                                               
fig.savefig(results_dir+'/Plots/Average_results_%s.png' % dir_name)

