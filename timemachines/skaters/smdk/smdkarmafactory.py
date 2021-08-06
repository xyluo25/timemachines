from timemachines.skaters.smdk.smdkinclusion import using_latest_simdkalman
if using_latest_simdkalman:

    from timemachines.skatertools.utilities.conventions import Y_TYPE, A_TYPE, R_TYPE, E_TYPE, T_TYPE, wrap
    from timemachines.skatertools.components.parade import parade
    from timemachines.skatertools.utilities.nonemath import nonecast
    import numpy as np
    import random
    from timemachines.skatertools.ensembling.precisionweightedskater import precision_weighted_skater
    from simdkalman.primitives import ddot, ddot_t_right, _update

    # Pronounced "sim-d-k ARMA factory", not "simd-karma-factory"

    # Not ready for prime time by any means


    def random_p(max_p: int):
        return random.choice(list(range(1, max_p + 1)))


    def random_q(max_q: int):
        return random.choice(list(range(1, max_q + 1)))


    def phi_decay(j):
        return 0.5 ** (j + 1)


    def theta_decay(j):
        return 0.5 ** (j + 1)


    def random_phi(p: int):
        return [(np.random.rand() - 0.5) * phi_decay(j) for j in range(p)]


    def random_theta(q: int):
        return [(np.random.rand() - 0.5) * theta_decay(j) for j in range(q)]


    def smkd_arma_agents_factory(y: Y_TYPE, n_agents: int, max_p: int, max_q:int, s, k: int, a: A_TYPE = None, t: T_TYPE = None,
                                 e: E_TYPE = None, r: R_TYPE = None):
        """

              max_p - Maximum AR order
              max_q - Maximum MA order

        """
        n_states = max(max_p, max_q+1)
        n_obs = 1  # May generalize later
        assert r is not None
        assert n_states >= 2
        y0 = wrap(y)[0]
        if not s.get('n_states'):
            s = smkd_arma_agents_initial_state(n_states=n_states, n_agents=n_agents, k=k, x0=y0)
        else:
            assert n_agents == s['n_agents']
            assert n_states == s['n_states']

        if y0 is None:
            return None, s, None
        else:
            # Mutation step - flag those needed system updates
            # Changes s['phi'], s['theta'], s['noise'], s['sigma'] and flags with s['stale']
            pass

            # Update system equations if params have mutated
            s = smdk_arma_update_stale(s,k)

            # Get time step, or default to 1 second
            if t is None:
                dt = 1
            else:
                if s.get('prev_t') is None:
                    s['prev_t'] = -1
                dt = t - s['prev_t']
                s['prev_t'] = t

            # Kalman updates
            prior_mean = ddot(s['A'], s['m'])  # A * m
            prior_cov = ddot(s['A'], ddot_t_right(s['P'], s['A'])) + dt * s['Q']  # A * P * A.t + Q
            posterior_mean, posterior_cov, K, ll = _update(prior_mean=prior_mean, prior_covariance=prior_cov,
                                                           observation_model=s['H'], observation_noise=s['R'],
                                                           log_likelihood=True)
            s['m'] = np.transpose(posterior_mean, axes=(0, 2, 1))
            s['P'] = posterior_cov

            # Compute k-step ahead predictions for each agent
            agent_xs = [[np.nan for _ in range(k)] for _ in range(n_agents)]
            agent_stds = [[np.nan for _ in range(k)] for _ in range(n_agents)]
            for j in range(k):
                if j == 0:
                    j_posterior_mean = posterior_mean
                else:
                    j_posterior_mean = ddot(s['powers_of_A'][j - 1, :, :, :], posterior_mean)
                j_y_hat = ddot(s['H'], j_posterior_mean)
                for ndx in range(n_agents):
                    agent_xs[ndx][k] = j_y_hat[ndx, 0, 0]

            # Update agent prediction parades and get their empirical standard errors
            for ndx in range(n_agents):
                _discard_bias, agent_stds[ndx], s['parades'][ndx] = parade(p=s['parades'][ndx], x=agent_xs[ndx], y=y0)

            # Create the exogenous vector that the precision weighted skater expects.
            # (i.e. y_for_pws[1:] has agent predictions interlaced with their empirical means)
            y_for_pws = [y0]
            s['fitness'] = [ 0.0 for _ in range(n_agents)]
            for agent_x, agent_std in zip(agent_xs, agent_stds):
                y_for_pws.append(agent_x[-1])
                y_for_pws.append(agent_std[-1])
                s['fitness'].append(agent_std[-1])

            # Call the precision weighted skater
            x, x_std, s['s_pks'] = precision_weighted_skater(y=y_for_pws, s=s['s_pws'], k=k, a=a, t=t, e=e)
            x_std_fallback = nonecast(x_std, fill_value=1.0)

            s['n_measurements'] += 1
            if s['n_measurements'] < 10:
                # Cold ... just puke naive forecasts
                return [y0] * k, [1.0] * k, s
            else:
                return x, x_std_fallback, s



    def smkd_arma_agents_initial_state(n_states, n_agents, k, x0:float):
        """
        :param n_states:    number of latest states is equal to max(p,q+1)
        :param n_agents:    number of independent ARMA models computed at once
        :param k:           number of steps ahead to forecast
        :param x0:          initial value for all latent lag states
        :return:
        """
        n_obs = 1 # dimension of observation (fixed at 1 for now)
        s = {'n_states': n_states,
             'n_agents': n_agents,
             'n_measurements': 0,
             'm': np.zeros((n_agents, 1, n_states)),
             'P': np.zeros((n_agents, n_states, n_states)),
             'H': np.zeros((n_agents, n_states, n_obs)),
             'R': np.zeros((n_agents, n_obs, n_obs)),
             'Q': np.zero((n_agents, n_states, n_states)),
             'A': np.zeros((n_agents, n_states, n_states)),
             'fitness': [1. for _ in range(n_agents)],
             'prev_t': None,
             's_pws': {}  # State for the precision weighted skater
             }
        ps = [random_p(n_states) for _ in range(n_agents)]
        qs = [random_q(n_states - 1) for _ in range(n_agents)]
        s['phi'] = [random_phi(p) for p in ps]
        s['theta'] = [random_theta(q) for q in qs]
        s['parades'] = [{} for _ in range(n_agents)]  # Track empirical errors individually (somewhat inefficient)
        s['stale'] = [True for _ in range(n_agents)]
        s['r_var'] = [np.exponential() ** 4 for _ in range(n_agents)]
        s['q_var'] = [np.exponential() ** 4 for _ in range(n_agents)]
        s['powers_of_A'] = np.array((k, n_agents, n_states, n_states))
        # Initialize random states
        for ndx in range(n_agents):
            s['m'][ndx, :, :] = np.array([[x0 for _ in range(n_states)]])
            s['P'][ndx, :, :] = (np.random.exponential() ** 4) * np.eye(n_states)
        return s


    def smdk_arma_update_stale(s,k):
        n_states = s['n_states']
        n_obs = 1
        for ndx, (pdtd, ph, tht, r_var, q_var) in enumerate(
                zip(s['updated'], s['phi'], s['theta'], s['r_var'], s['q_var'])):
            p = len(ph)
            q = len(tht)
            if not pdtd:
                A_ = np.zeros((n_states, n_states))
                A_[0, :p] = ph
                for j in range(n_states - 1):
                    A_[j + 1, j] = 1.
                s['A'][ndx, :, :] = A_
                H_ = np.zeros((n_states, 1))
                H_[0, 0] = 1
                H_[0, 1:q + 1] = ph
                s['H'][ndx, :, :] = H_
                Q_ = np.zeros((n_states, n_states))
                Q_[0, 0] = q_var
                s['Q'][ndx, :, :] = Q_
                R_ = np.ones((n_obs, n_obs))
                R_[0, 0] = r_var
                s['R'][ndx, :, :] = R_
                s['powers_of_A'][0, ndx, :, :] = A_
                for j in range(1, k):
                    s['powers_of_A'][j, ndx, :, :] = ddot(s['powers_of_A'][j - 1, ndx, :, :], A_)
        return s

