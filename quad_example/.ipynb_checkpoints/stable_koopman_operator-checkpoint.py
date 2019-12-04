import numpy as np
from numpy import sin, cos
from scipy.linalg import logm
from scipy.linalg import polar

NUM_STATE_OBS_ = 18
NUM_ACTION_OBS_ = 4
NUM_OBS_ = NUM_STATE_OBS_ + NUM_ACTION_OBS_

def psix(x):
    w1 = x[3];
    w2 = x[4];
    w3 = x[5];
    v1 = x[6];
    v2 = x[7];
    v3 = x[8];
    return np.array([
          x[0],x[1],x[2], # g
          x[3],x[4],x[5], # omega
          x[6],x[7],x[8], # v
          v3 * w2,
          v2 * w3,
          v3 * w1,
          v1 * w3,
          v2 * w1,
          v1 * w2,
          w2 * w3,
          w1 * w3,
          w1 * w2,
            ])

def psiu(x):
    return np.array([
        [1., 0., 0., 0.],
        [0., 1., 0., 0.,],
        [0., 0., 1., 0.,],
        [0., 0., 0., 1.,]])

class StableKoopmanOperator(object):

    def __init__(self, sampling_time, noise=1.0):
        self.noise = noise 
        self.sampling_time = sampling_time
        

        ### stable koopman setup
        self.S = np.eye(NUM_OBS_)
        self.K = np.random.normal(0., 1.0, size=(NUM_OBS_, NUM_OBS_))
        [self.U, self.B] = polar(self.K)

        # project 
        self.B = self.projectPSD(self.B)
        self.S = self.projectPSD(self.S)
       
        [self.U, _] = polar(self.U)

        self.alpha = 1e-5

        self.Kx = np.ones((NUM_STATE_OBS_, NUM_STATE_OBS_))
        self.Kx = np.random.normal(0., 1.0, size=self.Kx.shape) * noise 
        self.Ku = np.ones((NUM_STATE_OBS_, NUM_ACTION_OBS_))
        self.Ku = np.random.normal(0., 1.0, size=self.Ku.shape) * noise 
        self.counter = 0

    def projectPSD(self, Q, eps=0., delta=1.):
        Q = (Q + Q.T) / 2.0
        [e_vals, e_vecs] = np.linalg.eig(Q)
        e_vals_sat = np.clip(e_vals, eps, delta)
        return e_vecs.dot(np.diag(e_vals_sat)).dot(e_vecs.T)



    def clear_operator(self):
        self.counter = 0
        self.Kx = np.random.normal(0., 1.0, size=self.Kx.shape) * self.noise 
        self.Ku = np.random.normal(0., 1.0, size=self.Ku.shape) * self.noise 
        self.G = np.zeros(self.A.shape)
        self.K = np.zeros(self.A.shape)

    def compute_operator_from_data(self, datain, cdata, dataout):
        self.counter += 1

        X = np.concatenate([psix(datain), np.dot(psiu(datain), cdata)], axis=0).reshape(-1,1)
        Y = np.concatenate([psix(dataout), np.dot(psiu(dataout), cdata)], axis=0).reshape(-1,1)
        
        Sinv = np.linalg.inv(self.S)
        R = Sinv.dot(self.U).dot(self.B).dot(self.S).dot(X)

        gradS = -Sinv.T.dot(R-Y).dot(X.T).dot(self.S.T).dot(self.B.T).dot(self.U.T).dot(Sinv.T) \
                    + self.B.T.dot(self.U.T).dot(Sinv.T).dot((R-Y).dot(X.T))
        gradB = -Sinv.T.dot(Y - Sinv.dot(self.U).dot(self.B).dot(self.S).dot(X)).dot(X.T).dot(self.S.T).dot(self.B.T)
        gradU = -self.U.T.dot(Sinv.T).dot(Y - Sinv.dot(self.U).dot(self.B).dot(self.S).dot(X)).dot(X.T).dot(self.S.T)

        self.S -= self.alpha * gradS
        self.B -= self.alpha * gradB
        self.U -= self.alpha * gradU 

        self.S = self.projectPSD(self.S)
        self.B = self.projectPSD(self.B)
        [self.U, _] = polar(self.U)
        
        self.K = np.linalg.inv(self.S).dot(self.U).dot(self.B).dot(self.S)
        Kcont = np.real(logm(self.K, disp=False)[0]/self.sampling_time)
        self.Kx = Kcont[0:NUM_STATE_OBS_, 0:NUM_STATE_OBS_]
        self.Ku = Kcont[0:NUM_STATE_OBS_, NUM_STATE_OBS_:NUM_OBS_]
        
        self.alpha *= 0.99**self.counter
        
        print(np.linalg.norm(Y-np.dot(self.K, X)))
#         print(np.dot(self.K, X))

    def transform_state(self, state):
        return psix(state)

    def f(self, state, action):
        # state=psix(state)
        return np.dot(self.Kx, state) + np.dot(self.Ku, action)

    def g(self, state):
        return self.Ku

    def get_linearization(self):
        return self.Kx, self.Ku

    def step(self, state, action):
        return state + self.f(state, action) * self.sampling_time

    # def step(self, state, action):
    #     k1 = self.f(state, action) * self.sampling_time
    #     k2 = self.f(state + k1/2.0, action) * self.sampling_time
    #     k3 = self.f(state + k2/2.0, action) * self.sampling_time
    #     k4 = self.f(state + k3, action) * self.sampling_time
    #     return state + (k1 + 2.0 * (k2 + k3) + k4)/6.0


    def simulate(self, state, N, action_schedule=None, policy=None):

        trajectory = [state.copy()]
        ldx = [self.Kx for  i in range(N)]
        ldu = [self.g(state)]
        actions = []
        for i in range(N-1):
            if policy is not None:
                action = policy(state)
                actions.append(action.copy())
            if action_schedule is not None:
                action = action_schedule[i]
            state = self.step(state, action)
            ldu.append(self.g(state))
            trajectory.append(state.copy())
        return trajectory, ldx, ldu, actions


    def simulate_mixed_policy(self, x0, N, ustar, policy, tau, lam):

        x = [None] * N
        x[0] = x0.copy()
        _u = [None] * (N-1)
        for i in range(N-1):
            if  tau <= i <= tau+lam:
                ueval = ustar
            else:
                ueval = policy(x[i])
            _u[i] = ueval
            x[i+1] = self.step(x[i], ueval)
        return x, _u
