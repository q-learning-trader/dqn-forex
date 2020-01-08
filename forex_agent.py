import datetime
import random
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import numpy as np
from tensorflow import keras

from experience_replay import Replay
from forex_env import ForexEnv

layers = keras.layers
optimizers = keras.optimizers
models = keras.models

DAY_MAP = {'Monday': 0.1, 'Tuesday': 0.2, 'Wednesday': 0.3, 'Thursday': 0.4, 'Friday': 0.5}

"""
Few Assumptions:
- Does not do risk management, just trade
"""


class ForexAgent:
    def __init__(self, train_mode=True, balance=10000, lot=0.5):
        self.env = ForexEnv(
            pair='EURUSD', balance=balance, lot=lot, is_test=True,
            train_data=True, auto_reset_env=False
        )

        self.action_space_n = self.env.action_space_n
        self.state_space_n = self.env.state_space_n

        self.episodes = 1000
        self.train_mode = train_mode

        # Hyperparameters
        self.discount_factor = 0.99
        self.learning_rate = 0.001
        self.epsilon = 1.0
        self.epsilon_decay = 0.999
        self.epsilon_min = 0.01
        self.batch_size = 300

        # Experience replay
        self.experience = Replay(1000)
        self.exp_size_before_training = 100

        # NN models
        self.model = self.build_model()
        self.target_model = self.build_model()

        self.update_target_model()

        if not train_mode:
            self.model.load_weights('./save_model/EUR_USD_DQN_model.h5')

    def build_model(self):
        model = models.Sequential()
        model.add(layers.Dense(48, activation='relu', input_shape=(self.state_space_n,)))
        model.add(layers.Dense(48, activation='relu'))
        model.add(layers.Dense(self.action_space_n, activation='softmax'))
        model.summary()
        model.compile(loss='mse', optimizer=optimizers.Adam(lr=self.learning_rate), metrics=['accuracy'])
        return model

    def update_target_model(self):
        self.target_model.set_weights(self.model.get_weights())

    def predict(self, state):
        nn_output = self.model.predict(state)
        return np.argmax(nn_output[0])

    def get_action(self, state):
        if np.random.rand() <= self.epsilon and self.train_mode:
            return np.random.choice(self.env.action_space)
        print(np.array(state).shape)
        q_value = self.model.predict(state)
        return np.argmax(q_value[0])

    def push_to_experience(self, state, action, reward, next_state, done):
        self.experience.append(state, action, reward, next_state, done)
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

    def train_model(self):
        if self.experience.size < self.exp_size_before_training:
            return
        batch_size = min(self.batch_size, self.experience.size)
        states, actions, rewards, next_states, dones = self.experience.sample(batch_size)

        output = self.model.predict(states)
        target = self.target_model.predict(next_states)

        for i in range(batch_size):
            reward = rewards[i]
            # if rewards[i] > 0:
            #     reward = 10
            # elif rewards[i] < 0:
            #     reward = -10
            output[i][actions[i]] = reward
            if dones[i]:
                output[i][actions[i]] = reward
            else:
                #     We use 2 here, cos if it's not done, then it should always do nothing
                output[i][2] = reward + self.discount_factor * (np.amax(target[i]))

        self.model.fit(states, output, batch_size=batch_size, epochs=1, verbose=0)

    def plot_graph(self, x, y, path):
        # x = [datetime.datetime.strptime(d, '%Y-%m-%d').date() for d in x]
        # plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        # plt.gca().xaxis.set_major_locator(mdates.MonthLocator(interval=6 if not self.train_mode else 12))
        plt.plot(x, y)
        # plt.gcf().autofmt_xdate()
        plt.savefig(path)

    def start(self):
        acc_profits = 0
        acc_losses = 0
        took_trades = 0
        acc_trades = []
        acc_bal = []
        acc_trade_count_list = []
        total_trades_won = 0
        total_trades_lost = 0
        i = 0
        while True:
            try:
                done = False
                state = self.env.reset()
                peak_price = 0
                profits, losses, trades, bals, trade_count_list = 0, 0, [], [], []
                while not done:
                    action = self.get_action([state]) if not self.env.open_position_exists else None
                    # We want to send do_nothing as action, to speed up the process when a position is open already
                    next_state, reward, done, info = self.env.step(action)
                    state = next_state
                    if self.train_mode and action is not None:
                        """If is train mode"""
                        self.push_to_experience(state, action, reward, next_state, done)
                        self.train_model()
                    if done:
                        if self.train_mode:
                            """If is train mode"""
                            self.update_target_model()
                        if info == 'sl_hit':
                            peak_price = self.env.current_trade_lowest
                            losses -= reward
                            total_trades_lost += 1
                        if info == 'tp_hit':
                            peak_price = self.env.current_trade_highest
                            profits += reward
                            total_trades_won += 1

                        if info in ['sl_hit', 'tp_hit']:
                            took_trades += 1
                            trades.append(self.env.get_current_date())
                            bals.append(self.env.balance)
                            trade_count_list.append(took_trades)
                            # For plotting sake, and we want to plot only 20 days interval
                            if took_trades % 20 == 0:
                                acc_trades.append(self.env.get_current_date())
                                acc_bal.append(self.env.balance)
                                acc_trade_count_list.append(took_trades)
                            # End for plotting sake
                            print(f'Got P: {profits}, L: {losses} pips for trade {took_trades}')
                            print(f'Entered at {self.env.entry_price} and was exited at {peak_price}')
                            acc_profits += profits
                            acc_losses -= losses
                            print(f'Curr Acc Profit: {acc_profits}, Current Acc Loss: {acc_losses}, '
                                  f'Diff: {acc_profits - abs(acc_losses)}\n')

                    if took_trades % 50 == 0:
                        if self.train_mode:
                            self.plot_graph(acc_trade_count_list, acc_bal, './performances/eurusd_dqn.png')
                            self.plot_graph(trade_count_list, bals,
                                            f"./performances/eurusd_dqn_btw_{took_trades - 50}_and_{took_trades}.png"
                                            )
                            self.model.save_weights('./save_model/EUR_USD_DQN_model.h5')
                        else:
                            self.plot_graph(
                                acc_trade_count_list, acc_bal, './performances/eurusd_dqn_test_data.png'
                            )

                i += 1
            except IndexError as e:
                if self.train_mode:
                    self.plot_graph(acc_trade_count_list, acc_bal, './performances/eurusd_dqn.png')
                else:
                    self.plot_graph(acc_trade_count_list, acc_bal, './performances/eurusd_dqn_test_data.png')
                self.model.save_weights('./save_model/EUR_USD_DQN_model.h5')
                break

        print(f'Acc profits: {acc_profits} pips')
        print(f'Acc losses: {acc_losses} pips')


print(f'STARTING TO TRAIN MODEL.........')
ForexAgent().start()
# print(f'STARTING TO TEST MODEL.........')
# ForexAgent(train_mode=False, balance=1000, lot=0.1).start()
