# -*- coding: utf-8 -*-
"""
Created on Mon Jan 30 11:14:27 2023

@author: Ana
"""

import numpy as np
import h5py
from scipy import interpolate
from scipy import integrate
from scipy.stats import kstest
import scipy.optimize as opt
import matplotlib.pyplot as plt
import os
import errno

class Found_injections:
    """
    Class for an algorithm of GW detected found injections from signal templates 
    of binary black hole mergers
    
    Input: an h5py file with the parameters of every sample and the threshold for 
    the false alarm rate (FAR). The default value is thr = 1, which means we are 
    considering a signal as detected when FAR <= 1.

    """
    
    def __init__(self, file, thr = 1):
        
        assert isinstance(file, h5py._hl.files.File),\
        "Argument (file) must be an h5py file."
               
        self.data = file
        
        assert isinstance(thr, float) or isinstance(thr, int),\
        "Argument (thr) must be a float or an integrer."
        
        #Total number of generated injections
        self.Ntotal = file.attrs['total_generated'] 
        
        #Mass 1 and mass 2 values in the source frame in solar units
        self.m1 = file["injections/mass1_source"][:]
        self.m2 = file["injections/mass2_source"][:]
        
        #Redshift and luminosity distance [Mpc] values 
        self.z = file["injections/redshift"][:]
        self.dL = file["injections/distance"][:]
      
        #Joint mass sampling pdf (probability density function) values, p(m1,m2)
        self.m_pdf = file["injections/mass1_source_mass2_source_sampling_pdf"][:]
        
        #Redshift sampling pdf values, p(z), corresponding to a redshift defined by a flat Lambda-Cold Dark Matter cosmology
        self.z_pdf = file["injections/redshift_sampling_pdf"][:]
        
        H0 = 67.9 #km/sMpc
        c = 3e5 #km/s
        omega_m = 0.3065
        A = np.sqrt(omega_m * (1 + self.z)**3 + 1 - omega_m)
        dL_dif = (c * (1 + self.z) / H0) * (1/A)
        
        #Luminosity distance sampling pdf values, p(dL), computed for a flat Lambda-Cold Dark Matter cosmology from the z_pdf values
        self.dL_pdf = self.z_pdf / dL_dif
        
        #mass chirp
        self.Mc = (self.m1 * self.m2)**(3/5) / (self.m1 + self.m2)**(1/5) 
        
        #total mass (m1+m2)
        self.Mtot = self.m1 + self.m2
        
        #eta aka symmetric mass ratio
        mu = (self.m1 * self.m2) / (self.m1 + self.m2)
        self.eta = mu / self.Mtot
        
        #False alarm rate statistics from each pipeline
        self.far_pbbh = file["injections/far_pycbc_bbh"][:]
        self.far_gstlal = file["injections/far_gstlal"][:]
        self.far_mbta = file["injections/far_mbta"][:]
        self.far_pfull = file["injections/far_pycbc_hyperbank"][:]
        
        found_pbbh = self.far_pbbh <= thr
        found_gstlal = self.far_gstlal <= thr
        found_mbta = self.far_mbta <= thr
        found_pfull = self.far_pfull <= thr
        
        #indexes of the found injections
        self.found_any = found_pbbh | found_gstlal | found_mbta | found_pfull
        print(self.found_any.sum())      
        
        self.pow_m1 = file.attrs['pow_mass1']
        self.pow_m2 = file.attrs['pow_mass2']
        self.mmax = file.attrs['max_mass1']
        self.mmin = file.attrs['min_mass1']
        self.zmax = file.attrs['max_redshift']
        self.max_index = np.argmax(self.dL)
        self.dLmax = self.dL[self.max_index]
        
        index = np.random.choice(np.arange(len(self.dL)), 200, replace=False)
        if self.max_index not in index:
            index = np.insert(index, -1, self.max_index)
            
        try_dL = self.dL[index]
        try_dLpdf = self.dL_pdf[index]
    
        #we add 0 value
        inter_dL = np.insert(try_dL, 0, 0, axis=0)
        inter_dLpdf = np.insert(try_dLpdf, 0, 0, axis=0)
        self.interp_dL = interpolate.interp1d(inter_dL, inter_dLpdf)
        
        try_z = self.z[index]
        inter_z = np.insert(try_z, 0, 0, axis=0)
        
        #add a value for self.zmax
        new_dL = np.insert(inter_dL, -1, self.dLmax, axis=0)
        new_z = np.insert(inter_z, -1, self.zmax, axis=0)
        
        self.interp_z = interpolate.interp1d(new_dL, new_z)
        
        self.gamma_opt = -0.02726
        self.delta_opt = 0.13166
        self.emax_opt = 0.79928
        
        self.dmid_params_names = {'Dmid_mchirp': 'cte', 'Dmid_mchirp_expansion': ['cte', 'a20', 'a01', 'a21', 'a30']}
        self.emax_params_names = {'emax' : ['gamma_opt, delta_opt, b_0, b_1, b_2'] }
        print('finished initializing')
    
    #now we define methods for this class
    
    #def sigmoid(self, dL, dLmid, gamma = -0.23168, delta = 0.16617, emax = 0.7795166, alpha = 2.05):
    def sigmoid(self, dL, dLmid, emax , gamma , delta , alpha = 2.05):
        """
        Sigmoid function used to estime the probability of detection of bbh events

        Parameters
        ----------
        dL : 1D array of the luminosity distance.
        dLmid : dL at which Pdet = 0.5.
        gamma : parameter controling the shape of the curve. The default is -0.18395.
        delta : parameter controling the shape of the curve. The default is 0.1146989.
        alpha : parameter controling the shape of the curve. The default is 2.05.
        emax : parameter controling the shape of the curve. The default is 0.967.

        Returns
        -------
        array of detection probability.

        """
        frac = dL / dLmid
        denom = 1. + frac ** alpha * \
            np.exp(gamma * (frac - 1.) + delta * (frac**2 - 1.))
        return emax / denom
    
    def Dmid_mchirp(self, m1, m2, z, cte):
        """
        Dmid values (distance where Pdet = 0.5) as a function of the masses 
        in the detector frame (our first guess)

        Parameters
        ----------
        m1 : mass1 
        m2: mass2
        z : redshift
        cte : parameter that we will be optimizing
        
        Returns
        -------
        Dmid(m1,m2) in the detector's frame

        """
        m1_det = m1 * (1 + z) 
        m2_det = m2 * (1 + z)
        
        Mc = (m1_det * m2_det)**(3/5) / (m1_det + m2_det)**(1/5)
        
        return cte * Mc**(5/6)
    
    def Dmid_mchirp_expansion(self, m1, m2, z, params):
        """
        Dmid values (distance where Pdet = 0.5) as a function of the masses 
        in the detector frame (our first guess)

        Parameters
        ----------
        m1 : mass1 
        m2: mass2
        z : redshift
        params : parameters that we will be optimizing
        
        Returns
        -------
        Dmid(m1,m2) in the detector's frame

        """
        cte , a_20, a_01, a_21, a_30 = params
        
        m1_det = m1 * (1 + z) 
        m2_det = m2 * (1 + z)
        M = m1_det + m2_det
        eta = m1*m2 / (m1+m2)**2
        
        Mc = (m1_det * m2_det)**(3/5) / (m1_det + m2_det)**(1/5)
        
        pol = cte *(1+ a_20 * M**2 / 2 + a_01 * (1 - 4*eta) + a_21 * M**2 * (1 - 4*eta) / 2 + a_30 * M**3)
        
        return pol * Mc**(5/6)
    
    def emax(self, m1, m2, params):
        Mtot = m1 + m2
        b_0, b_1, b_2 = params
        return 1 - np.exp(b_0 + b_1 * Mtot + b_2 * Mtot**2)
    
    # def emax(self, m1, m2, params):
    #     Mtot = m1 + m2
    #     b_0, b_1 = params
    #     #y=1-np.exp(-0.9-0.003*(x-80)-0.0003*(x-80)**2)
    #     return 1 - np.exp(b_0 + b_1 * Mtot )
    
 
    def fun_m_pdf(self, m1, m2):
        """
        Function for the mass pdf aka p(m1,m2)

        Returns
        -------
        A continuous function which describes p(m1,m2)

        """
        # if m2 > m1:
        #   return 0
        
        mmin = self.mmin ; mmax = self.mmax
        alpha = self.pow_m1 ; beta = self.pow_m2
        
        m1_norm = (1. + alpha) / (mmax ** (1. + alpha) - mmin ** (1. + alpha))
        m2_norm = (1. + beta) / (m1 ** (1. + beta) - mmin ** (1. + beta))
        
        return m1**alpha * m2**beta * m1_norm * m2_norm
    
    
    def Nexp(self, dmid_fun, dmid_params, shape_params = None, emax_fun = None):
        """
        Expected number of found injections, computed as a 
        triple integral of p(dL)*p(m1,m2)*sigmoid( dL, Dmid(m1,m2, dL, cte) )*Ntotal
        
        Note that in order to make the integral, we had to use an interpolation for the redshift, just so we can
        write Dmid as a function of dL and then integrate over d(dL)

        Parameters
        ----------
        params : parameters of the Dmid function

        Returns
        -------
        Expected number of found injections

        """
        # quad_fun = lambda m1, m2, dL_int: self.Ntotal * self.fun_m_pdf(m1, m2) *  \
        #     self.interp_dL(dL_int) * self.sigmoid(dL_int, self.Dmid_inter(m1, m2, dL_int, params)) 
        
        # lim_m2 = lambda m1: [self.mmin, m1]
        # return integrate.nquad( quad_fun, [[self.mmin, self.mmax], lim_m2, [0, self.dLmax]], full_output=True)[0]
        
        # we try this sencond method for Nexp
        
        dmid = getattr(Found_injections, dmid_fun)
        
        if emax_fun is None:
            gamma, delta, emax = shape_params[0], shape_params[1], shape_params[2]
            Nexp = np.sum(self.sigmoid(self.dL, dmid(self, self.m1, self.m2, self.z, dmid_params), emax, gamma, delta))
            
        else:
            emax = getattr(Found_injections, emax_fun)
            gamma, delta = shape_params[0], shape_params[1]
            emax_params = shape_params[2:]
            Nexp = np.sum(self.sigmoid(self.dL, dmid(self, self.m1, self.m2, self.z, dmid_params), emax(self, self.m1, self.m2, emax_params), gamma, delta))
        
        # elif shape_params is None and emax_params is not None:
        #     emax = getattr(Found_injections, emax_fun)
        #     Nexp = np.sum(self.sigmoid(self.dL, dmid(self, self.m1, self.m2, self.z, dmid_params), emax(self, self.m1, self.m2, emax_params)))
        
        # else:
        #     Nexp = np.sum(self.sigmoid(self.dL, dmid(self, self.m1, self.m2, self.z, dmid_params)))
            
        #print(Nexp)
        return Nexp
        
    def lamda(self, dmid_fun, dmid_params, shape_params = None, emax_fun = None):
        """
        Number density at found injections

        Parameters
        ----------
        params : parameters of the Dmid function

        Returns
        -------
        Number density at found injections aka lambda(D,m1,m2)

        """
        dL = self.dL[self.found_any]
        dL_pdf = self.dL_pdf[self.found_any]
        m_pdf = self.m_pdf[self.found_any]
        z = self.z[self.found_any]
        m1 = self.m1[self.found_any]
        m2 = self.m2[self.found_any]
        
        dmid = getattr(Found_injections, dmid_fun)
        
        if emax_fun is None:
            gamma, delta, emax = shape_params[0], shape_params[1], shape_params[2]
            lamda = self.sigmoid(dL, dmid(self, m1, m2, z, dmid_params), emax, gamma, delta) * m_pdf * dL_pdf * self.Ntotal
        
        else:
            emax = getattr(Found_injections, emax_fun)
            gamma, delta = shape_params[0], shape_params[1]
            emax_params = shape_params[2:]
            lamda = self.sigmoid(dL, dmid(self, m1, m2, z, dmid_params), emax(self, m1, m2, emax_params), gamma, delta) * m_pdf * dL_pdf * self.Ntotal
            
        # elif shape_params is None and emax_fun is not None:
        #     emax = getattr(Found_injections, emax_fun)
        #     lamda = self.sigmoid(dL, dmid(self, m1, m2, z, dmid_params), emax(self, m1, m2, emax_params)) * m_pdf * dL_pdf * self.Ntotal
        
        # else:
        #     lamda = self.sigmoid(dL, dmid(self, m1, m2, z, dmid_params)) * m_pdf * dL_pdf * self.Ntotal
        
        return lamda
    
    def logL(self, dmid_fun, dmid_params, shape_params = None, emax_fun = None):
        """
        log likelihood of the expected density of found injections

        Parameters
        ----------
        in_param : parameters that will be optimized. It should be cte of self.Dmid(cte).
        We will use exp(cte) in the minimization, so we have to remember then to take log(opt_cte).

        Returns
        -------
        TYPE
            DESCRIPTION.

        """
        
        # if shape_params is not None:
        #     shape_params = [shape_params[0], shape_params[1], shape_params[2]]
            
        lnL = -self.Nexp(dmid_fun, dmid_params, shape_params, emax_fun) + np.sum(np.log(self.lamda(dmid_fun, dmid_params, shape_params, emax_fun)))
        #print(lnL)
        return lnL
        
    
    def MLE_dmid(self, methods, dmid_fun, params_guess, shape_params, emax_fun = None):
        """
        minimization of -logL on dmid

        Parameters
        ----------
        cte_guess : initial guess value for cte of Dmid
        methods : scipy method used to minimize -logL

        Returns
        -------
        cte_res : optimized value for cte of Dmid.
        -min_likelihood : maximum log likelihood. 

        """
        res = opt.minimize(fun=lambda in_param: -self.logL(dmid_fun, in_param, shape_params, emax_fun), 
                           x0=np.array([params_guess]), 
                           args=(), 
                           method=methods)
        
        params_res = res.x
        min_likelihood = res.fun                
        return params_res, -min_likelihood
    
    def MLE_shape(self, methods, dmid_fun, params_dmid, params_shape_guess, update = False):
        """
        minimization of -logL on shape params (with emax as a cte)

        Parameters
        ----------
        cte_guess : initial guess value for cte of Dmid
        methods : scipy method used to minimize -logL

        Returns
        -------
        cte_res : optimized value for cte of Dmid.
        -min_likelihood : maximum log likelihood. 

        """
        gamma_guess, delta_guess, emax_guess = params_shape_guess
        
        res = opt.minimize(fun=lambda in_param: -self.logL(dmid_fun, params_dmid, in_param), 
                           x0=np.array([gamma_guess, delta_guess, emax_guess]), 
                           args=(), 
                           method=methods)
        
        gamma, delta, emax = res.x
        min_likelihood = res.fun  
        
        if update: self.gamma_opt, self.delta_opt, self.emax_opt = gamma, delta, emax 

        return gamma, delta, emax, -min_likelihood
    
    def MLE_emax(self, methods, dmid_fun, params_dmid, params_shape_guess, emax_fun, update = False):
        """
        minimization of -logL on shape params (with emax as a function of masses)

        Parameters
        ----------
        cte_guess : initial guess value for cte of Dmid
        methods : scipy method used to minimize -logL

        Returns
        -------
        cte_res : optimized value for cte of Dmid.
        -min_likelihood : maximum log likelihood. 

        """
        
        res = opt.minimize(fun=lambda in_param: -self.logL(dmid_fun, params_dmid, in_param, emax_fun), 
                           x0=np.array([params_shape_guess]), 
                           args=(), 
                           method=methods)
        
        gamma, delta = res.x[:2]
        min_likelihood = res.fun  
        
        if update: self.gamma_opt, self.delta_opt = gamma, delta

        return res.x, -min_likelihood
    
    # def MLE_difev(self, dmid_fun, emax_fun, bounds, maxiter=50, popsize=100):
        
    #     def lnL(x):
    #         lnL = -self.Nexp(dmid_fun, emax_fun, x) + np.sum(np.log(self.lamda(dmid_fun, emax_fun, x)))
    #         print(lnL)
    #         return lnL
        
    #     result = opt.differential_evolution(lnL, bounds, maxiter=maxiter, popsize=popsize)
    #     params_opt = result.x
    #     maxL = result.fun
    #     return params_opt, maxL
    
    def joint_MLE(self, methods, dmid_fun, params_dmid, params_shape, emax_fun = None, precision = 1e-2):
        
        total_lnL = np.zeros([1])
        all_gamma = []
        all_delta = []
        all_emax = []
        all_dmid_params = np.zeros([1,len(params_dmid)])
        all_emax_params = np.zeros([1,len(params_shape[2:])]) 
        params_emax = None if emax_fun is None else params_shape[2:]
        
        for i in range(0, 10000):
            
            params_dmid, maxL_1 = data.MLE_dmid(methods, dmid_fun, params_dmid, params_shape, emax_fun)
            all_dmid_params = np.vstack([all_dmid_params, params_dmid])
            
            if emax_fun is None:
                gamma_opt, delta_opt, emax_opt, maxL_2 = data.MLE_shape(methods, dmid_fun, params_dmid, params_shape, update = True)
                all_gamma.append(gamma_opt); all_delta.append(delta_opt)
                all_emax.append(emax_opt); total_lnL = np.append(total_lnL, maxL_2)
                
                params_shape = [gamma_opt, delta_opt, emax_opt]
            
            elif emax_fun is not None:
                params_shape, maxL_2 = data.MLE_emax(methods, dmid_fun, params_dmid, params_shape, emax_fun, update = True)
                gamma_opt, delta_opt = params_shape[:2]
                params_emax = params_shape[2:]
                all_gamma.append(gamma_opt); all_delta.append(delta_opt)
                all_emax_params = np.vstack([all_emax_params, params_emax])
                total_lnL = np.append(total_lnL, maxL_2)
            
            print('\n', maxL_2)
            print(np.abs( total_lnL[i+1] - total_lnL[i] ))
            
            if np.abs( total_lnL[i+1] - total_lnL[i] ) <= precision : break
        
        print('\nNumber of needed iterations with precision <= %s : %s (+1 since it starts on 0)' %(precision, i))

        total_lnL = np.delete(total_lnL, 0)
        
        if emax_fun is None:
            shape_results = np.column_stack((all_gamma, all_delta, all_emax, total_lnL))
            shape_header = 'gamma_opt, delta_opt, emax_opt, maxL'
            name_dmid = f'{dmid_fun}/joint_fit_dmid.dat'
            np.savetxt(f'{dmid_fun}/joint_fit_shape.dat', shape_results, header = shape_header, fmt='%s')
        
        elif emax_fun is not None:
            shape_results = np.column_stack((all_gamma, all_delta, np.delete(all_emax_params, 0, axis=0), total_lnL))
            shape_header = f'{self.emax_params_names[emax_fun]} , maxL'
            name_dmid = f'{dmid_fun}/joint_fit_dmid_emaxfun.dat'
            np.savetxt(f'{dmid_fun}/joint_fit_shape_emaxfun.dat', shape_results, header = shape_header, fmt='%s')
        
        
        all_dmid_params = np.delete(all_dmid_params, 0, axis=0)
        dmid_results = np.column_stack((all_dmid_params, total_lnL))
        dmid_header = f'{self.dmid_params_names[dmid_fun]} , maxL'
        np.savetxt(name_dmid, dmid_results, header = dmid_header, fmt='%s')
        
        return


    def cumulative_dist(self, dmid_fun, dmid_params, shape_params, var = 'dL'):
        
        dmid = getattr(Found_injections, dmid_fun)
        dic = {'dL': self.dL, 'Mc': self.Mc, 'Mtot': self.Mtot, 'eta': self.eta}
        
        gamma, delta, emax = shape_params[0], shape_params[1], shape_params[2]
           
        #cumulative distribution over the desired variable
        indexo = np.argsort(dic[var])
        varo = dic[var][indexo]
        dLo = self.dL[indexo]
        m1o = self.m1[indexo]
        m2o = self.m2[indexo]
        zo = self.z[indexo]
        cmd = np.cumsum(self.sigmoid(dLo, dmid(self, m1o, m2o, zo, dmid_params), emax, gamma, delta))
        
        #found injections
        var_found = dic[var][self.found_any]
        indexo_found = np.argsort(var_found)
        var_foundo = var_found[indexo_found]
        real_found_inj = np.arange(len(var_foundo))+1
    
        plt.figure()
        plt.plot(varo, cmd, '.', markersize=2, label='model')
        plt.plot(var_foundo, real_found_inj, '.', markersize=2, label='found injections')
        plt.xlabel(f'${var}^*$')
        plt.ylabel('Cumulative found injections')
        plt.legend(loc='best')
        name=f'{dmid_fun}/{var}_cumulative.png'
        plt.savefig(name, format='png')
        
        #KS test
        pdet = self.sigmoid(self.dL, dmid(self, self.m1, self.m2, self.z, dmid_params), emax, gamma, delta)
        
        def cdf(x):
            values = [np.sum(pdet[dic[var]<value])/np.sum(pdet) for value in x]
            return np.array(values)
            
        return kstest(var_foundo, lambda x: cdf(x) )
    
    
    def binned_cumulative_dist(self, nbins, dmid_fun, dmid_params, shape_params, var_cmd , var_binned, emax_fun = None):
        
        emax_dic = {'None' : 'cmds', 'emax' : 'emax_exp_cmds'}
        
        try:
            os.mkdir(f'{dmid_fun}/{emax_dic[emax_fun]}')
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
                
        try:
            os.mkdir(f'{dmid_fun}/{emax_dic[emax_fun]}/{var_binned}_bins')
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
                
        try:
            os.mkdir(f'{dmid_fun}/{emax_dic[emax_fun]}/{var_binned}_bins/{var_cmd}_cmd')
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
        
        if emax_fun is not None:
            emax = getattr(Found_injections, emax_fun)
            emax_params = shape_params[2:]
            gamma, delta = shape_params[:2]
            
        else:
            gamma, delta, emax = shape_params
                
        dmid = getattr(Found_injections, dmid_fun)
        bin_dic = {'dL': self.dL, 'Mc': self.Mc, 'Mtot': self.Mtot, 'eta': self.eta}
        
        #sort data
        data_not_sorted = bin_dic[var_binned]
        index = np.argsort(data_not_sorted)
        data = data_not_sorted[index]
        
        dLo = self.dL[index]; m1o = self.m1[index]; m2o = self.m2[index]; zo = self.z[index]
        Mco = self.Mc[index]; Mtoto = self.Mtot[index]; etao = self.eta[index]
        found_any_o = self.found_any[index]
        
        #create bins with equally amount of data
        def equal_bin(N, m):
            sep = (N.size/float(m))*np.arange(1,m+1)
            idx = sep.searchsorted(np.arange(N.size))
            return idx[N.argsort().argsort()]
        
        index_bins = equal_bin(data, nbins)
        
        print(f'\n{var_binned} bins:\n')
        
        for i in range(nbins):
            #get data in each bin
            data_inbin = data[index_bins==i]
            dL_inbin = dLo[index_bins==i]
            m1_inbin = m1o[index_bins==i]
            m2_inbin = m2o[index_bins==i]
            z_inbin = zo[index_bins==i]
            
            Mc_inbin = Mco[index_bins==i]
            Mtot_inbin = Mtoto[index_bins==i]
            eta_inbin = etao[index_bins==i]
            
            cmd_dic = {'dL': dL_inbin, 'Mc': Mc_inbin, 'Mtot': Mtot_inbin, 'eta': eta_inbin}
        
            #cumulative distribution over the desired variable
            indexo = np.argsort(cmd_dic[var_cmd])
            varo = cmd_dic[var_cmd][indexo]
            dL = dL_inbin[indexo]
            m1 = m1_inbin[indexo]
            m2 = m2_inbin[indexo]
            z = z_inbin[indexo]
            
            if emax_fun is not None:
                cmd = np.cumsum(self.sigmoid(dL, dmid(self, m1, m2, z, dmid_params), emax(self, m1, m2, emax_params), gamma, delta))
            else:
                cmd = np.cumsum(self.sigmoid(dL, dmid(self, m1, m2, z, dmid_params), emax, gamma, delta))
            
            #found injections
            found_inj_index_inbin = found_any_o[index_bins==i]
            found_inj_inbin = cmd_dic[var_cmd][found_inj_index_inbin]
            indexo_found = np.argsort(found_inj_inbin)
            found_inj_inbin_sorted = found_inj_inbin[indexo_found]
            real_found_inj = np.arange(len(found_inj_inbin_sorted ))+1
        
            plt.figure()
            plt.plot(varo, cmd, '.', markersize=2, label='model')
            plt.plot(found_inj_inbin_sorted, real_found_inj, '.', markersize=2, label='found injections')
            plt.xlabel(f'${var_cmd}^*$')
            plt.ylabel('Cumulative found injections')
            plt.legend(loc='best')
            plt.title(f'{var_binned} bin {i} : {data_inbin[0]:.6} - {data_inbin[-1]:.6}')
            name=f'{dmid_fun}/{emax_dic[emax_fun]}/{var_binned}_bins/{var_cmd}_cmd/{i}.png'
            plt.savefig(name, format='png')
            plt.close()
            
            #KS test
            if emax_fun is not None:
                pdet = self.sigmoid(dL_inbin, dmid(self, m1_inbin, m2_inbin, z_inbin, dmid_params), emax(self, m1_inbin, m2_inbin, emax_params), gamma, delta)
            else:    
                pdet = self.sigmoid(dL_inbin, dmid(self, m1_inbin, m2_inbin, z_inbin, dmid_params), emax, gamma, delta)
            
            def cdf(x):
                values = [np.sum(pdet[cmd_dic[var_cmd]<value])/np.sum(pdet) for value in x]
                return np.array(values)
            
            stat, pvalue = kstest(found_inj_inbin_sorted, lambda x: cdf(x) )
            
            print(f'{var_cmd} KStest in {i} bin: statistic = %s , pvalue = %s' %(stat, pvalue))
        
        print('')   
        return 
            
        

plt.close('all')

file = h5py.File('endo3_bbhpop-LIGO-T2100113-v12.hdf5', 'r')


data = Found_injections(file)

# function for dmid we wanna use
dmid_fun = 'Dmid_mchirp_expansion'
emax_fun = 'emax'

try:
    os.mkdir(f'{dmid_fun}')
except OSError as e:
    if e.errno != errno.EEXIST:
        raise
        
try:
    os.mkdir(f'{dmid_fun}/shape')
except OSError as e:
    if e.errno != errno.EEXIST:
        raise
        
cte_guess = 99
a20_guess= 0.0001
a01_guess= -0.4
a21_guess = -0.0001
#a22_guess = -0.0002
a30_guess = 0.0001

# b0_guess = -3
# b1_guess = -0.05
# b2_guess = 0.0003

b0_guess = -2.4
#b1_guess = 0.09
b1_guess = 0
b2_guess = 0

gamma_guess = -0.02726
delta_guess = 0.13166
emax_guess = 0.79928

shape_guess = [gamma_guess, delta_guess, emax_guess]

params_guess = {'Dmid_mchirp': cte_guess, 'Dmid_mchirp_expansion': [cte_guess, a20_guess, a01_guess, a21_guess, a30_guess]}
params_names = {'Dmid_mchirp': 'cte', 'Dmid_mchirp_expansion': ['cte', 'a20', 'a01', 'a21', 'a30']}



########## MLE DMID ##########

# params_opt, maxL = data.MLE_dmid('Nelder-Mead', dmid_fun, params_guess[dmid_fun])
# print(params_opt)

# results = np.hstack((params_opt, maxL))
# header = f'{params_names[dmid_fun]} , maxL'
# np.savetxt(f'{dmid_fun}/dmid(m)_results_2method.dat', [results], header = header, fmt='%s')

# params_dmid = np.loadtxt(f'{dmid_fun}/dmid(m)_results_2method.dat')[:-1]

########## MLE SHAPE ##########

# gamma_opt, delta_opt, emax_opt, maxL = data.MLE_shape('Nelder-Mead', dmid_fun, params_dmid, shape_guess, update = True)
# print(gamma_opt, delta_opt, emax_opt)

# results = np.column_stack((gamma_opt, delta_opt, emax_opt, maxL))
# header = 'gamma_opt, delta_opt, emax_opt, maxL'
# np.savetxt(f'{dmid_fun}/shape/opt_shape_params.dat', results, header = header, fmt='%s')

#gamma_opt, delta_opt, emax_opt = np.loadtxt(f'{dmid_fun}/shape/opt_shape_params.dat')[:-1]

########## JOINT FIT #########
#data.joint_MLE('Nelder-Mead', dmid_fun, params_guess[dmid_fun], shape_guess, emax_fun = None, precision = 1e-2)

# # ~~~~~~~~~ THESE LINES ARE NECESSARY TO DO THE JOINT FIT WITH EMAX FUN ~~~~~~~~~

# params_dmid = np.loadtxt(f'{dmid_fun}/joint_fit_dmid.dat')[-1, :-1]
# gamma_opt, delta_opt, emax_opt = np.loadtxt(f'{dmid_fun}/joint_fit_shape.dat')[-1, :-1]
# params_shape = [gamma_opt, delta_opt, emax_opt]

# shape_guess_emax = [gamma_opt, delta_opt, b0_guess, b1_guess, b2_guess]

# # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ 

# print('\nparams_dmid:\n', params_dmid)
# print('\ngamma, delta, emax:\n', gamma_opt, delta_opt, emax_opt, '\n')

########## JOINT FIT WITH EMAX FUNCTION ###########
# data.joint_MLE('Nelder-Mead', dmid_fun, params_dmid, shape_guess_emax, emax_fun, precision = 1e-2)

params_dmid = np.loadtxt(f'{dmid_fun}/joint_fit_dmid_emaxfun.dat')[-1, :-1]
params_shape = np.loadtxt(f'{dmid_fun}/joint_fit_shape_emaxfun.dat')[-1, :-1]
gamma_opt, delta_opt = params_shape[:2]
params_emax = params_shape[2:]

print('\nparams_dmid:\n', params_dmid)
print('\ngamma, delta, b0, b1, b2:\n', gamma_opt, delta_opt, params_emax, '\n')

########## KS TEST ##########

plt.close('all')

# stat_dL, pvalue_dL = data.cumulative_dist(dmid_fun, params_dmid, params_shape, 'dL')
# print('\ndL KStest: statistic = %s , pvalue = %s' %(stat_dL, pvalue_dL))

# stat_Mtot, pvalue_Mtot = data.cumulative_dist(dmid_fun, params_dmid, params_shape, 'Mtot')
# print('Mtot KStest: statistic = %s , pvalue = %s' %(stat_Mtot, pvalue_Mtot))

# stat_Mc, pvalue_Mc = data.cumulative_dist(dmid_fun, params_dmid, params_shape, 'Mc')
# print('Mc KStest: statistic = %s , pvalue = %s' %(stat_Mc, pvalue_Mc))

# stat_eta, pvalue_eta = data.cumulative_dist(dmid_fun, params_dmid, params_shape, 'eta') 
# print('eta KStest: statistic = %s , pvalue = %s' %(stat_eta, pvalue_eta))

#binned cumulative dist analysis
nbins = 5
data.binned_cumulative_dist(nbins, dmid_fun, params_dmid, params_shape, 'dL', 'eta', emax_fun)
data.binned_cumulative_dist(nbins, dmid_fun, params_dmid, params_shape, 'Mtot', 'eta', emax_fun)
data.binned_cumulative_dist(nbins, dmid_fun, params_dmid, params_shape, 'Mc', 'eta', emax_fun)
data.binned_cumulative_dist(nbins, dmid_fun, params_dmid, params_shape, 'eta', 'eta', emax_fun)

#bounds = [ (50, 150), (-1,1), (-1, 1), (-1, 1), (-1,1) ]


###### PLOT TO CHECK EPSILON(DL) WITH OPT PARAMETERS #######
#gamma_opt, delta_opt, emax_opt = np.loadtxt(f'{dmid_fun}/joint_fit_shape.dat')[-1, :-1]

# plt.figure(figsize=(7,6))
# plt.plot(data.dL, data.sigmoid(data.dL, data.Dmid_mchirp_expansion(data.m1, data.m2, data.z, params_dmid), emax_opt, gamma_opt, delta_opt), '.')
# t = ('gamma = %.3f , delta = %.3f , emax = %.3f' %(gamma_opt, delta_opt, emax_opt) )
# plt.title(t)
# plt.xlabel('dL')
# plt.ylabel(r'$\epsilon (dL, dmid(m), \gamma_{opt}, \delta_{opt}, emax_{opt})$')
# plt.show()
#plt.savefig(f'{dmid_fun}/opt_epsilon_plot.png')

###### PLOT TO CHECK EPSILON(DL) WITH OPT PARAMETERS and emax fun #######
#gamma_opt, delta_opt, emax_opt = np.loadtxt(f'{dmid_fun}/joint_fit_shape.dat')[-1, :-1]

plt.figure(figsize=(7,6))
plt.plot(data.dL, data.sigmoid(data.dL, data.Dmid_mchirp_expansion(data.m1, data.m2, data.z, params_dmid), data.emax(data.m1, data.m2, params_emax), gamma_opt, delta_opt), '.')
plt.xlabel('dL')
plt.ylabel(r'$\epsilon (dL, dmid(m), emax(m), \gamma_{opt}, \delta_{opt})$')
plt.show()
plt.savefig(f'{dmid_fun}/opt_epsilon_plot_emaxfun.png')

x = np.linspace(0,data.mmax*2, 500)
y = 1 - np.exp(params_emax[0] + params_emax[1] * x + params_emax[2] * x**2)
plt.figure()
plt.plot(x, y, '.')
plt.ylim(0.2, 2)
plt.grid()
plt.xlabel('Mtot')
plt.ylabel('emax(m)')
plt.savefig(f'{dmid_fun}/emax(m).png')

