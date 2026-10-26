"""The recorded Read response for 1904.12072v3 and a synthetic source that holds its quotes."""

import json
from pathlib import Path

from phy.card import CardDraft

RECORDED = json.loads(
    (
        Path(__file__).parent / "fixtures" / "anthropic" / "read_1904.12072v3_response.json"
    ).read_text()
)
RECORDED_DRAFT = CardDraft.model_validate_json(RECORDED["content"][0]["text"])

# Synthetic flattened text holding the recorded draft's quotes, in raw forms that differ from
# the quotes only canonically. One quote is split by a blank line, and one is missing.
SEED_LIKE = r"""\documentclass[aps,prd]{revtex4-1}
\begin{document}
\begin{abstract}
A key feature of the approach is that models trained to a fixed acceptance rate do not
experience critical slowing down in the sampling stage.
\end{abstract}

\section{Introduction}
Here, a {\it normalizing flow model} is used to define a proposal distribution
$\tilde{p}(\phi)$ for a generative Metropolis-Hastings algorithm.

\section{Flow-based MCMC\label{sec:flowMCMC}}
We assume the Markov chain is initialized with a sample from the stationary distribution
$p(\phi)$ throughout.

\section{Application to $\phi^4$ theory}
\subsection{Results}
In this work, the flow-based MCMC algorithm detailed in Section~\ref{sec:flowMCMC} was
applied to $\phi^4$ theory in two dimensions with $L=\{6,8,10,12,14\}$ lattice sites in each
dimension. For simplicity in this initial work, all parameters were chosen to lie in the
symmetric phase. We compare against HMC as well as standard local Metropolis~\cite{Wolff1996}
and Hybrid Monte Carlo (HMC)~\citep{Duane1987HMC} algorithms at matched parameters.

For all observables, the values computed using the flow-based MCMC ensembles are consistent
within statistical uncertainties with those computed using the standard methods.
In each case, the critical exponent was $0.3\lesssim z_\mathcal{O}\lesssim 2.0$.
In comparison, for the flow-based MCMC ensembles at a fixed acceptance, the critical exponent

was found to be consistent with zero, with the autocorrelation time observable-independent.
Moreover, Figure~\ref{fig:errorscaling} shows that the statistical uncertainties of the
observables scale as $1 / \sqrt{N}$ with the number of samples $N$, as expected for
decorrelated samples. Since the the mean acceptance rate was used as the stopping criterion
for training these models, we compare at fixed acceptance.

\section{Conclusions}
In this work, all models were trained using one to two GPU-weeks, with the larger lattices
incurring the most computational cost. However, the efficiency with which the training step
of this approach can be scaled to larger model sizes, and to more complicated theories such
as QCD, remains to be studied. This asymptotic scaling is a result of the simple model
architecture used in this proof-of-principle study.
\end{document}
"""
