#!/usr/bin/env python
"""
Some tests for the likelihood function class.

tests to do:
    setting of parameters, by coord, by for-all, checking pars sets
    testing the likelihood for specified pars
    getting ancestral probs
    simulating sequence (not possible to verify values as random)
    
    checking that the object resets on tree change, model change, etc
"""
import warnings

warnings.filterwarnings("ignore", "Motif probs overspecified")
warnings.filterwarnings("ignore", "Model not reversible")
warnings.filterwarnings("ignore", "Ignoring tree edge lengths")

import os
from numpy import ones, dot

from cogent3.evolve import substitution_model, predicate
from cogent3 import DNA, LoadSeqs, LoadTree
from cogent3.util.unit_test import TestCase, main
from cogent3.maths.matrix_exponentiation import PadeExponentiator as expm
from cogent3.maths.stats.information_criteria import aic, bic
from cogent3.evolve.models import JTT92

Nucleotide = substitution_model.Nucleotide
MotifChange = predicate.MotifChange

__author__ = "Peter Maxwell and Gavin Huttley"
__copyright__ = "Copyright 2007-2012, The Cogent Project"
__credits__ = ["Peter Maxwell", "Gavin Huttley", "Rob Knight",
               "Matthew Wakefield", "Brett Easton"]
__license__ = "GPL"
__version__ = "1.5.3-dev"
__maintainer__ = "Gavin Huttley"
__email__ = "gavin.huttley@anu.edu.au"
__status__ = "Production"

base_path = os.getcwd()
data_path = os.path.join(base_path, 'data')

ALIGNMENT = LoadSeqs(
    moltype=DNA,
    filename=os.path.join(data_path, 'brca1.fasta'))

OTU_NAMES = ["Human", "Mouse", "HowlerMon"]

########################################################
# some funcs for assembling Q-matrices for 'manual' calc


def isTransition(motif1, motif2):
    position = getposition(motif1, motif2)
    a, b = motif1[position], motif2[position]
    transitions = {('A', 'G'): 1, ('C', 'T'): 1}
    pair = (min(a, b), max(a, b))

    return pair in transitions


def numdiffs_position(motif1, motif2):
    assert len(motif1) == len(motif2),\
        "motif1[%s] & motif2[%s] have inconsistent length" %\
        (motif1, motif2)

    ndiffs, position = 0, -1
    for i in range(len(motif1)):
        if motif1[i] != motif2[i]:
            position = i
            ndiffs += 1

    return ndiffs == 1, position


def isinstantaneous(motif1, motif2):
    if motif1 != motif2 and (motif1 == '-' * len(motif1) or
                             motif2 == '-' * len(motif1)):
        return True
    ndiffs, position = numdiffs_position(motif1, motif2)
    return ndiffs


def getposition(motif1, motif2):
    ndiffs, position = numdiffs_position(motif1, motif2)
    return position

##############################################################
# funcs for testing the monomer weighted substitution matrices
_root_probs = lambda x: dict([(n1 + n2, p1 * p2)
                              for n1, p1 in list(x.items()) for n2, p2 in list(x.items())])


def make_p(length, coord, val):
    """returns a probability matrix with value set at coordinate in
    instantaneous rate matrix"""
    Q = ones((4, 4), float) * 0.25  # assumes equi-frequent mprobs at root
    for i in range(4):
        Q[i, i] = 0.0
    Q[coord] *= val
    row_sum = Q.sum(axis=1)
    scale = 1 / (.25 * row_sum).sum()
    for i in range(4):
        Q[i, i] -= row_sum[i]
    Q *= scale
    return expm(Q)(length)


class LikelihoodCalcs(TestCase):
    """tests ability to calculate log-likelihoods for several
    substitution models."""

    def setUp(self):
        self.alignment = ALIGNMENT.take_seqs(OTU_NAMES)[0: 42]
        self.tree = LoadTree(tip_names=OTU_NAMES)

    def _makeLikelihoodFunction(self, submod, translate=False, **kw):
        alignment = self.alignment
        if translate:
            alignment = alignment.get_translation()
        calc = submod.makeLikelihoodFunction(self.tree, **kw)
        calc.setAlignment(alignment)
        calc.set_param_rule('length', value=1.0, is_constant=True)
        if not translate:
            calc.set_param_rule('kappa', value=3.0, is_constant=True)
        return calc

    def test_no_seq_named_root(self):
        """root is a reserved name"""
        aln = self.alignment.take_seqs(self.alignment.names[:4])
        aln = aln.todict()
        one = aln.pop("Mouse")
        aln["root"] = one
        aln = LoadSeqs(data=aln)
        submod = Nucleotide()
        tree = LoadTree(treestring="%s" % str(tuple(aln.names)))
        lf = submod.makeLikelihoodFunction(tree)
        try:
            lf.setAlignment(aln)
        except AssertionError:
            pass

        collection = aln.degap().named_seqs
        collection.pop("Human")
        tree = LoadTree(treestring="%s" % str(tuple(collection.keys())))
        lf = submod.makeLikelihoodFunction(tree, aligned=False)
        try:
            lf.setSequences(collection)
        except AssertionError:
            pass

    def test_binned_gamma(self):
        """just rate is gamma distributed"""
        submod = substitution_model.Codon(
            predicates={'kappa': 'transition', 'omega': 'replacement'},
            ordered_param='rate', distribution='gamma', mprob_model='tuple')
        lf = self._makeLikelihoodFunction(submod, bins=3)
        try:
            values = list(lf.get_param_value_dict(
                ['bin'])['omega_factor'].values())
        except KeyError:
            # there shouldn't be an omega factor
            pass
        values = list(lf.get_param_value_dict(['bin'])['rate'].values())
        obs = round(sum(values) / len(values), 6)
        self.assertEqual(obs, 1.0)
        self.assertEqual(len(values), 3)
        shape = lf.get_param_value('rate_shape')

    def test_binned_gamma_ordered_param(self):
        """rate is gamma distributed omega follows"""
        submod = substitution_model.Codon(
            predicates={'kappa': 'transition', 'omega': 'replacement'},
            ordered_param='rate', partitioned_params='omega',
            distribution='gamma', mprob_model='tuple')
        lf = self._makeLikelihoodFunction(submod, bins=3)
        values = list(lf.get_param_value_dict(['bin'])['omega_factor'].values())
        self.assertEqual(round(sum(values) / len(values), 6), 1.0)
        self.assertEqual(len(values), 3)
        shape = lf.get_param_value('rate_shape')

    def test_binned_partition(self):
        submod = substitution_model.Codon(
            predicates={'kappa': 'transition', 'omega': 'replacement'},
            ordered_param='rate', partitioned_params='omega',
            distribution='free', mprob_model='tuple')
        lf = self._makeLikelihoodFunction(submod, bins=3)
        values = list(lf.get_param_value_dict(['bin'])['omega_factor'].values())
        self.assertEqual(round(sum(values) / len(values), 6), 1.0)
        self.assertEqual(len(values), 3)

    def test_complex_binned_partition(self):
        submod = substitution_model.Codon(
            predicates={'kappa': 'transition', 'omega': 'replacement'},
            ordered_param='kappa', partitioned_params=['omega'],
            mprob_model='tuple')
        lf = self._makeLikelihoodFunction(submod,
                                          bins=['slow', 'fast'])
        lf.set_param_rule('kappa', value=1.0, is_constant=True)
        lf.set_param_rule('kappa', edge="Human", init=1.0, is_constant=False)
        values = list(lf.get_param_value_dict(['bin'])['kappa_factor'].values())
        self.assertEqual(round(sum(values) / len(values), 6), 1.0)
        self.assertEqual(len(values), 2)

    def test_codon(self):
        """test a three taxa codon model."""
        submod = substitution_model.Codon(
            equal_motif_probs=True,
            do_scaling=False,
            motif_probs=None,
            predicates={'kappa': 'transition', 'omega': 'replacement'},
            mprob_model='tuple')

        likelihood_function = self._makeLikelihoodFunction(submod)
        likelihood_function.set_param_rule('omega', value=0.5, is_constant=True)
        evolve_lnL = likelihood_function.get_log_likelihood()
        self.assertFloatEqual(evolve_lnL, -80.67069614541883)

    def test_nucleotide(self):
        """test a nucleotide model."""
        submod = Nucleotide(
            equal_motif_probs=True,
            do_scaling=False,
            motif_probs=None,
            predicates={'kappa': 'transition'})
        # now do using the evolve
        likelihood_function = self._makeLikelihoodFunction(
            submod)
        self.assertEqual(likelihood_function.getNumFreeParams(), 0)
        evolve_lnL = likelihood_function.get_log_likelihood()
        self.assertFloatEqual(evolve_lnL, -157.49363874840455)

    def test_discrete_nucleotide(self):
        """test that partially discrete nucleotide model can be constructed, 
        differs from continuous, and has the expected number of free params"""
        submod = Nucleotide(
            equal_motif_probs=True,
            do_scaling=False,
            motif_probs=None,
            predicates={'kappa': 'transition'})
        likelihood_function = self._makeLikelihoodFunction(
            submod, discrete_edges=['Human'])
        self.assertEqual(likelihood_function.getNumFreeParams(), 12)
        evolve_lnL = likelihood_function.get_log_likelihood()
        self.assertNotEqual(evolve_lnL, -157.49363874840455)

    def test_dinucleotide(self):
        """test a dinucleotide model."""
        submod = substitution_model.Dinucleotide(
            equal_motif_probs=True,
            do_scaling=False,
            motif_probs=None,
            predicates={'kappa': 'transition'},
            mprob_model='tuple')
        likelihood_function = self._makeLikelihoodFunction(submod)
        evolve_lnL = likelihood_function.get_log_likelihood()
        self.assertFloatEqual(evolve_lnL, -102.48145536663735)

    def test_protein(self):
        """test a protein model."""
        submod = substitution_model.Protein(
            do_scaling=False, equal_motif_probs=True)

        likelihood_function = self._makeLikelihoodFunction(submod,
                                                           translate=True)

        evolve_lnL = likelihood_function.get_log_likelihood()
        self.assertFloatEqual(evolve_lnL, -89.830370754876185)


class LikelihoodFunctionTests(TestCase):
    """tests for a tree analysis class. Various tests to create a tree analysis class,
    set parameters, and test various functions.
    """

    def setUp(self):
        self.submodel = Nucleotide(
            do_scaling=True, model_gaps=False, equal_motif_probs=True,
            predicates={'beta': 'transition'})

        self.data = LoadSeqs(
            filename=os.path.join(data_path, 'brca1_5.paml'),
            moltype=self.submodel.moltype)

        self.tree = LoadTree(
            filename=os.path.join(data_path, 'brca1_5.tree'))

    def _makeLikelihoodFunction(self, **kw):
        lf = self.submodel.makeLikelihoodFunction(self.tree, **kw)
        lf.set_param_rule('beta', is_independent=True)
        lf.setAlignment(self.data)
        return lf

    def _setLengthsAndBetas(self, likelihood_function):
        for (species, length) in [
                ("DogFaced", 0.1),
                ("NineBande", 0.2),
                ("Human", 0.3),
                ("HowlerMon", 0.4),
                ("Mouse", 0.5)]:
            likelihood_function.set_param_rule("length", value=length,
                                             edge=species, is_constant=True)
        for (species1, species2, length) in [
                ("Human", "HowlerMon", 0.7),
                ("Human", "Mouse", 0.6)]:
            LCA = self.tree.get_connecting_node(species1, species2).name
            likelihood_function.set_param_rule("length", value=length,
                                             edge=LCA, is_constant=True)

        likelihood_function.set_param_rule("beta", value=4.0, is_constant=True)

    def test_information_criteria(self):
        """test get information criteria from a model."""
        lf = self._makeLikelihoodFunction()
        nfp = lf.getNumFreeParams()
        lnL = lf.get_log_likelihood()
        l = len(self.data)
        self.assertFloatEqual(lf.getAic(), aic(lnL, nfp))
        self.assertFloatEqual(lf.getAic(second_order=True),
                              aic(lnL, nfp, l))

        self.assertFloatEqual(lf.getBic(), bic(lnL, nfp, l))

    def test_result_str(self):
        # actualy more a test of self._setLengthsAndBetas()
        likelihood_function = self._makeLikelihoodFunction()
        self._setLengthsAndBetas(likelihood_function)
        self.assertEqual(str(likelihood_function),
                         """Likelihood Function Table\n\
======
  beta
------
4.0000
------
=============================
     edge    parent    length
-----------------------------
    Human    edge.0    0.3000
HowlerMon    edge.0    0.4000
   edge.0    edge.1    0.7000
    Mouse    edge.1    0.5000
   edge.1      root    0.6000
NineBande      root    0.2000
 DogFaced      root    0.1000
-----------------------------
===============
motif    mprobs
---------------
    T    0.2500
    C    0.2500
    A    0.2500
    G    0.2500
---------------""")

        likelihood_function = self._makeLikelihoodFunction(digits=2, space=2)
        self.assertEqual(str(likelihood_function),
                         """Likelihood Function Table\n\
===============================
     edge  parent  length  beta
-------------------------------
    Human  edge.0    1.00  1.00
HowlerMon  edge.0    1.00  1.00
   edge.0  edge.1    1.00  1.00
    Mouse  edge.1    1.00  1.00
   edge.1    root    1.00  1.00
NineBande    root    1.00  1.00
 DogFaced    root    1.00  1.00
-------------------------------
=============
motif  mprobs
-------------
    T    0.25
    C    0.25
    A    0.25
    G    0.25
-------------""")

    def test_calclikelihood(self):
        likelihood_function = self._makeLikelihoodFunction()
        self._setLengthsAndBetas(likelihood_function)
        self.assertAlmostEqual(-250.686745262,
                               likelihood_function.get_log_likelihood(), places=9)

    def test_g_statistic(self):
        likelihood_function = self._makeLikelihoodFunction()
        self._setLengthsAndBetas(likelihood_function)
        self.assertAlmostEqual(230.77670557,
                               likelihood_function.get_G_statistic(), places=6)

    def test_ancestralsequences(self):
        likelihood_function = self._makeLikelihoodFunction()
        self._setLengthsAndBetas(likelihood_function)
        result = likelihood_function.reconstruct_ancestral_seqs()['edge.0']
        a_column_with_mostly_Ts = -1
        motif_G = 2
        self.assertAlmostEqual(2.28460181711e-05,
                               result[a_column_with_mostly_Ts][motif_G], places=8)
        lf = self.submodel.makeLikelihoodFunction(
            self.tree, bins=['low', 'high'])
        lf.set_param_rule('beta', bin='low', value=0.1)
        lf.set_param_rule('beta', bin='high', value=10.0)
        lf.setAlignment(self.data)
        result = lf.reconstruct_ancestral_seqs()

    def test_likely_ancestral(self):
        """excercising the most likely ancestral sequences"""
        likelihood_function = self._makeLikelihoodFunction()
        self._setLengthsAndBetas(likelihood_function)
        result = likelihood_function.likely_ancestral_seqs()

    def test_simulate_alignment(self):
        "Simulate DNA alignment"
        likelihood_function = self._makeLikelihoodFunction()
        self._setLengthsAndBetas(likelihood_function)
        simulated_alignment = likelihood_function.simulate_alignment(
            20, exclude_internal=False)
        self.assertEqual(len(simulated_alignment), 20)
        self.assertEqual(len(simulated_alignment.get_seq_names()), 8)

    def test_simulateHetergeneousAlignment(self):
        "Simulate substitution-heterogeneous DNA alignment"
        lf = self.submodel.makeLikelihoodFunction(
            self.tree, bins=['low', 'high'])
        lf.set_param_rule('beta', bin='low', value=0.1)
        lf.set_param_rule('beta', bin='high', value=10.0)
        simulated_alignment = lf.simulate_alignment(100)

    def test_simulatePatchyHetergeneousAlignment(self):
        "Simulate patchy substitution-heterogeneous DNA alignment"
        lf = self.submodel.makeLikelihoodFunction(
            self.tree, bins=['low', 'high'], sites_independent=False)
        lf.set_param_rule('beta', bin='low', value=0.1)
        lf.set_param_rule('beta', bin='high', value=10.0)
        simulated_alignment = lf.simulate_alignment(100)

    def test_simulate_alignment2(self):
        "Simulate alignment with dinucleotide model"
        al = LoadSeqs(data={'a': 'ggaatt', 'c': 'cctaat'})
        t = LoadTree(treestring="(a,c);")
        sm = substitution_model.Dinucleotide(mprob_model='tuple')
        lf = sm.makeParamController(t)
        lf.setAlignment(al)
        simalign = lf.simulate_alignment()
        self.assertEqual(len(simalign), 6)

    def test_simulate_alignment3(self):
        """Simulated alignment with gap-induced ambiguous positions
        preserved"""
        t = LoadTree(treestring='(a:0.4,b:0.3,(c:0.15,d:0.2)edge.0:0.1)root;')
        al = LoadSeqs(data={
            'a': 'g--cactat?',
            'b': '---c-ctcct',
            'c': '-a-c-ctat-',
            'd': '-a-c-ctat-'})
        sm = Nucleotide(recode_gaps=True)
        lf = sm.makeParamController(t)
        # pc.set_constant_lengths()
        lf.setAlignment(al)
        # print lf.simulate_alignment(sequence_length=10)
        simulated = lf.simulate_alignment()
        self.assertEqual(len(simulated.get_seq_names()), 4)
        import re
        self.assertEqual(
            re.sub('[ATCG]', 'x', simulated.todict()['a']),
            'x??xxxxxx?')

    def test_simulate_alignment_root_sequence(self):
        """provide a root sequence for simulating an alignment"""
        def use_root_seq(root_sequence):
            al = LoadSeqs(data={'a': 'ggaatt', 'c': 'cctaat'})
            t = LoadTree(treestring="(a,c);")
            sm = substitution_model.Dinucleotide(mprob_model='tuple')
            lf = sm.makeParamController(t)
            lf.setAlignment(al)
            simalign = lf.simulate_alignment(exclude_internal=False,
                                            root_sequence=root_sequence)
            root = simalign.named_seqs['root']
            self.assertEqual(str(root), str(root_sequence))

        root_sequence = DNA.make_sequence('GTAATT')
        use_root_seq(root_sequence)  # as a sequence instance
        use_root_seq('GTAATC')  # as a string

    def test_pc_initial_parameters(self):
        """Default parameter values from original annotated tree"""
        likelihood_function = self._makeLikelihoodFunction()
        self._setLengthsAndBetas(likelihood_function)
        tree = likelihood_function.get_annotated_tree()
        lf = self.submodel.makeParamController(tree)
        lf.setAlignment(self.data)
        self.assertEqual(lf.get_param_value("length", "Human"), 0.3)
        self.assertEqual(lf.get_param_value("beta", "Human"), 4.0)

    def test_set_par_all(self):
        likelihood_function = self._makeLikelihoodFunction()
        likelihood_function.set_param_rule("length", value=4.0, is_constant=True)
        likelihood_function.set_param_rule("beta", value=6.0, is_constant=True)
        self.assertEqual(str(likelihood_function),
                         """Likelihood Function Table
======
  beta
------
6.0000
------
=============================
     edge    parent    length
-----------------------------
    Human    edge.0    4.0000
HowlerMon    edge.0    4.0000
   edge.0    edge.1    4.0000
    Mouse    edge.1    4.0000
   edge.1      root    4.0000
NineBande      root    4.0000
 DogFaced      root    4.0000
-----------------------------
===============
motif    mprobs
---------------
    T    0.2500
    C    0.2500
    A    0.2500
    G    0.2500
---------------""")

        # self.submodel.setScaleRule("ts",['beta'])
        #self.submodel.setScaleRule("tv",['beta'], exclude_pars = True)
        self.assertEqual(str(likelihood_function),
                         """Likelihood Function Table
======
  beta
------
6.0000
------
=============================
     edge    parent    length
-----------------------------
    Human    edge.0    4.0000
HowlerMon    edge.0    4.0000
   edge.0    edge.1    4.0000
    Mouse    edge.1    4.0000
   edge.1      root    4.0000
NineBande      root    4.0000
 DogFaced      root    4.0000
-----------------------------
===============
motif    mprobs
---------------
    T    0.2500
    C    0.2500
    A    0.2500
    G    0.2500
---------------""")

    def test_get_motif_probs(self):
        likelihood_function = self._makeLikelihoodFunction()
        mprobs = likelihood_function.get_motif_probs()
        assert hasattr(mprobs, 'keys'), mprobs
        keys = list(mprobs.keys())
        keys.sort()
        obs = self.submodel.getMotifs()
        obs.sort()
        self.assertEqual(obs, keys)

    def test_get_annotated_tree(self):
        likelihood_function = self._makeLikelihoodFunction()
        likelihood_function.set_param_rule(
            "length", value=4.0, edge="Human", is_constant=True)
        result = likelihood_function.get_annotated_tree()
        self.assertEqual(result.get_node_matching_name(
            'Human').params['length'], 4.0)
        self.assertEqual(result.get_node_matching_name('Human').length, 4.0)

    def test_getparamsasdict(self):
        likelihood_function = self._makeLikelihoodFunction()
        likelihood_function.set_name("TEST")
        self.assertEqual(str(likelihood_function),
                         """TEST
=======================================
     edge    parent    length      beta
---------------------------------------
    Human    edge.0    1.0000    1.0000
HowlerMon    edge.0    1.0000    1.0000
   edge.0    edge.1    1.0000    1.0000
    Mouse    edge.1    1.0000    1.0000
   edge.1      root    1.0000    1.0000
NineBande      root    1.0000    1.0000
 DogFaced      root    1.0000    1.0000
---------------------------------------
===============
motif    mprobs
---------------
    T    0.2500
    C    0.2500
    A    0.2500
    G    0.2500
---------------""")
        self.assertEqual(likelihood_function.get_param_value_dict(['edge']), {
            'beta': {'NineBande': 1.0, 'edge.1': 1.0, 'DogFaced': 1.0, 'Human': 1.0,
                     'edge.0': 1.0, 'Mouse': 1.0, 'HowlerMon': 1.0},
            'length': {'NineBande': 1.0, 'edge.1': 1.0, 'DogFaced': 1.0, 'Human': 1.0,
                       'edge.0': 1.0, 'Mouse': 1.0, 'HowlerMon': 1.0}})

    def test_get_statistics_from_empirical_model(self):
        """should return valid dict from an empirical substitution model"""
        submod = JTT92()
        aln = self.data.get_translation()

        lf = submod.makeLikelihoodFunction(self.tree)
        lf.setAlignment(aln)
        stats = lf.get_param_value_dict(['edge'], params=['length'])

    def test_constant_to_free(self):
        """excercise setting a constant param rule, then freeing it"""
        # checks by just trying to make the calculator
        lf = self.submodel.makeLikelihoodFunction(self.tree)
        lf.setAlignment(self.data)
        lf.set_param_rule('beta', is_constant=True, value=2.0,
                        edges=['NineBande', 'DogFaced'], is_clade=True)
        lf.set_param_rule('beta', init=2.0, is_constant=False,
                        edges=['NineBande', 'DogFaced'], is_clade=True)

    def test_get_psub_rate_matrix(self):
        """lf should return consistent rate matrix and psub"""
        lf = self.submodel.makeLikelihoodFunction(self.tree)
        lf.setAlignment(self.data)
        Q = lf.get_rate_matrix_for_edge('NineBande')
        P = lf.get_psub_for_edge('NineBande')
        self.assertFloatEqual(expm(Q.array)(1.0), P.array)

        # should fail for a discrete Markov model
        dm = substitution_model.DiscreteSubstitutionModel(DNA.alphabet)
        lf = dm.makeLikelihoodFunction(self.tree)
        lf.setAlignment(self.data)
        self.assertRaises(Exception, lf.get_rate_matrix_for_edge, 'NineBande')

    def test_make_discrete_markov(self):
        """lf ignores tree lengths if a discrete Markov model"""
        t = LoadTree(treestring='(a:0.4,b:0.3,(c:0.15,d:0.2)edge.0:0.1)root;')
        dm = substitution_model.DiscreteSubstitutionModel(DNA.alphabet)
        lf = dm.makeLikelihoodFunction(t)

if __name__ == '__main__':
    main()
