# I keep this file as a skeleton until we have real hardware data to evaluate against.
# Defining the function signatures now lets routes and tests import and call them
# without breaking, while making the expected interface explicit for whoever
# implements the bodies later.

from __future__ import annotations


def load_model(model_path: str) -> object:
    """Load a trained anomaly-detection model from a joblib file on disk.

    Args:
        model_path: Absolute or relative path to the .joblib model file produced
                    by backend/ml/train.py.

    Returns:
        The deserialized model object (e.g. IsolationForest or LocalOutlierFactor).

    # TODO: use joblib.load(model_path) and validate that the returned object
    # has a predict() method before returning it.
    """
    raise NotImplementedError("TODO: implement after first hardware data collected")


def evaluate_precision_recall(model, X_test, y_true) -> dict:
    """Run the model on X_test and compute classification metrics against y_true.

    Args:
        model:  A fitted sklearn-compatible estimator with a predict() method.
                Anomaly predictions are expected as -1 (anomaly) or 1 (normal).
        X_test: 2-D array-like of shape (n_samples, n_features) - the same feature
                columns used during training.
        y_true: 1-D array-like of shape (n_samples,) with ground-truth binary labels
                where 1 means anomaly and 0 means normal.

    Returns:
        A dict with keys "precision", "recall", "f1", and "support" so callers
        do not need to import sklearn directly.

    # TODO: call model.predict(X_test), remap -1->1 and 1->0, then use
    # sklearn.metrics.precision_recall_fscore_support with average='binary'.
    """
    raise NotImplementedError("TODO: implement after first hardware data collected")


def plot_anomaly_distribution(scores: list, output_path: str) -> None:
    """Save a histogram of raw anomaly scores to a PNG file.

    Args:
        scores:      List of float anomaly scores, one per telemetry sample.
                     Higher values indicate more anomalous readings.
        output_path: File path where the PNG will be written, e.g.
                     "reports/anomaly_distribution.png".

    # TODO: use matplotlib.pyplot to create a histogram with a vertical line at
    # ANOMALY_SCORE_THRESHOLD (read from env), then save with plt.savefig(output_path).
    """
    raise NotImplementedError("TODO: implement after first hardware data collected")


def generate_report(
    model_path: str,
    data_path: str,
    output_path: str,
) -> None:
    """Run the full evaluation pipeline and write a summary report to disk.

    This is the single entry point intended to be called from the command line
    or a scheduled job once we have labelled hardware data.

    Args:
        model_path:  Path to the .joblib model file - passed directly to load_model().
        data_path:   Path to a CSV file with the same columns as the telemetry table.
                     Must include a "is_anomaly" column as ground-truth labels.
        output_path: Directory where the report PNG and JSON summary will be written.
                     Created if it does not exist.

    Pipeline steps (to be implemented):
      1. load_model(model_path)
      2. Read and preprocess data_path with the same scaler used in train.py
      3. evaluate_precision_recall() to get metrics
      4. plot_anomaly_distribution() to save histogram
      5. Write a JSON summary file alongside the histogram

    # TODO: implement steps above once backend/ml/train.py has been validated on
    # real sensor readings from the first deployed Phaemos node.
    """
    raise NotImplementedError("TODO: implement after first hardware data collected")
