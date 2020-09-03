from shap.utils import safe_isinstance
from shap.maskers import Text, Partition
import shap.datasets
import matplotlib.pyplot as pl
import sklearn
import nlp 
import transformers
import xgboost 
import numpy as np
from tqdm.auto import tqdm
import time


class SequentialPerturbation():
    def __init__(self, f, masker, sort_order, score_function, perturbation):
        self.f = f
        self.masker = masker
        self.sort_order = sort_order
        self.score_function = score_function
        self.perturbation = perturbation
        
        # If the user just gave a dataset as the masker
        # then we make a masker that perturbs features independently
        if type(self.masker) == np.ndarray:
            self.masker_data = self.masker
            self.masker = lambda mask, x: x * mask + self.masker_data * np.invert(mask)
        
        # define our sort order
        if self.sort_order == "positive":
            self.sort_order_map = lambda x: np.argsort(-x)
        elif self.sort_order == "negative":
            self.sort_order_map = lambda x: np.argsort(x)
        elif self.sort_order == "absolute":
            self.sort_order_map = lambda x: np.argsort(-abs(x))
        else:
            raise ValueError("sort_order must be either \"positive\", \"negative\", or \"absolute\"!")
            
        self.score_values = []
        self.score_aucs = []
        self.labels = []
    
    def score(self, attributions, X, y=None, label=None, silent=False):
        
        if label is None:
            label = "Score %d" % len(self.score_values)
        
        # convert dataframes
        if safe_isinstance(X, "pandas.core.series.Series"):
            X = X.values
        elif safe_isinstance(self.masker, "pandas.core.frame.DataFrame"):
            X = X.values
            
        # convert all single-sample vectors to matrices
        if not hasattr(attributions[0], "__len__"):
            attributions = np.array([attributions])
        if not hasattr(X[0], "__len__"):
            X = np.array([X])
        
        # loop over all the samples
        pbar = None
        start_time = time.time()
        svals = []
        for i in range(len(X)):
            mask = np.ones(len(X[i]), dtype=np.bool) * (self.perturbation == "remove")
            ordered_inds = self.sort_order_map(attributions[i])
            
            # compute the fully masked score
            values = np.zeros(len(X[i])+1)
            masked = self.masker(mask, X[i])
            values[0] = self.score_function(None if y is None else y[i], self.f(masked).mean(0))

            # loop over all the features
            curr_val = None
            for j in range(len(X[i])):
                oind = ordered_inds[j]
                
                # keep masking our inputs until there are none more to mask
                if not ((self.sort_order == "positive" and attributions[i][oind] <= 0) or \
                        (self.sort_order == "negative" and attributions[i][oind] >= 0)):
                    mask[oind] = self.perturbation == "keep"
                    masked = self.masker(mask, X[i])
                    curr_val = self.score_function(None if y is None else y[i], self.f(masked).mean(0))
                values[j+1] = curr_val
            svals.append(values)

            if pbar is None and time.time() - start_time > 5:
                pbar = tqdm(total=len(X), disable=silent, leave=False)
                pbar.update(i+1)
            if pbar is not None:
                pbar.update(1)
        if pbar is not None:
            pbar.close()
            
        self.score_values.append(np.array(svals))
        
        if self.sort_order == "negative":
            curve_sign = -1
        else:
            curve_sign = 1
        
        self.score_aucs.append(np.array([
            sklearn.metrics.auc(np.linspace(0, 1, len(svals[i])), curve_sign*(svals[i] - svals[i][0]))
            for i in range(len(svals))
        ]))
        
        self.labels.append(label)
        
        xs = np.linspace(0, 1, 100)
        curves = np.zeros((len(self.score_values[-1]), len(xs)))
        for j in range(len(self.score_values[-1])):
            xp = np.linspace(0, 1, len(self.score_values[-1][j]))
            yp = self.score_values[-1][j]
            curves[j,:] = np.interp(xs, xp, yp)
        ys = curves.mean(0)
        
        return xs, ys
        
    def plot(self):
        
        for i in range(len(self.score_values)):
            xs = np.linspace(0, 1, 100)
            curves = np.zeros((len(self.score_values[i]), len(xs)))
            for j in range(len(self.score_values[i])):
                xp = np.linspace(0, 1, len(self.score_values[i][j]))
                yp = self.score_values[i][j]
                curves[j,:] = np.interp(xs, xp, yp)
            ys = curves.mean(0)
            pl.plot(
                xs, ys, label=self.labels[i] + " AUC %0.4f" % self.score_aucs[i].mean()
            )
        if (self.sort_order == "negative") != (self.perturbation == "remove"):
            pl.gca().invert_yaxis()
        pl.legend()
        pl.show()

# Example 

X,y = shap.datasets.adult()
model = xgboost.XGBClassifier().fit(X, y)

f = lambda x: model.predict(x, output_margin=True)
masker = Partition(X[:500])
explainer = shap.Explainer(f, masker)(X[:500])
shap_values = explainer.values
data = explainer.data
score_function = lambda y, out: out
sort_order = 'absolute'
perturbation = 'keep'

sp = SequentialPerturbation(f, masker, sort_order, score_function, perturbation)
sp.score(shap_values, data)
sp.plot()