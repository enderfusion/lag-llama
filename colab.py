import subprocess
import os
import sys
from itertools import islice
from matplotlib import pyplot as plt
import matplotlib.dates as mdates
from tqdm import tqdm
import torch
from gluonts.evaluation import make_evaluation_predictions, Evaluator
from gluonts.dataset.repository.datasets import get_dataset
from gluonts.dataset.pandas import PandasDataset
import warnings
import pandas as pd
import pickle
from data_prep import *
import zipfile
import pickle
from pytorch_lightning import Trainer
from pytorch_lightning.callbacks import ModelCheckpoint,EarlyStopping
from sklearn.model_selection import train_test_split
from gluonts.dataset.common import TrainDatasets
import logging
logging.basicConfig(level=logging.DEBUG)
#matplotlib.use('TkAgg')  # Use TkAgg backend for interactive plotting
matplotlib.use('Agg')  # Use TkAgg backend for interactive plotting
import warnings
warnings.filterwarnings("ignore", message="Using `json`-module for json-handling. Consider installing one of `orjson`, `ujson` to speed up serialization and deserialization.")
warnings.filterwarnings("ignore", message="Using `json`-module for json-handling. Consider installing one of `orjson`, `ujson` to speed up serialization and deserialization.")

# Add the cloned repository to the system path
sys.path.append(os.path.abspath('./lag-llama'))

# Import the LagLlamaEstimator after adding the repository to the path
from lag_llama.gluon.estimator import LagLlamaEstimator
from lag_llama.gluon.estimator import ValidationSplitSampler




def initialize():
    #git_executable = r"C:\Program Files\Git\cmd\git.exe"  # Update this path based on your installation
    subprocess.run([git_executable, "clone", "https://github.com/time-series-foundation-models/lag-llama/"])
    # Install requirements
    subprocess.run(["pip", "install", "-r", "lag-llama/requirements.txt"])
    sys.path.append(os.path.abspath('./lag-llama'))  # Add the cloned repository to the system path
    subprocess.run(["huggingface-cli", "download", "time-series-foundation-models/Lag-Llama", "lag-llama.ckpt", "--local-dir", "lag-llama"])  # Download the model checkpoint
    subprocess.run([git_executable, "config", "--global", "user.name", "Andrew McCalip"])
    subprocess.run([git_executable, "config", "--global", "user.email", "Andrew McCalip"])

# Ensure the repository is cloned and path is added before importing LagLlamaEstimator
#initialize()
sys.path.append(os.path.abspath('./lag-llama'))  # Ensure the path is added
from lag_llama.gluon.estimator import LagLlamaEstimator
 

def get_lag_llama_predictions(dataset, prediction_length, context_length, num_samples, device="cpu", batch_size=64, nonnegative_pred_samples=True):
    ckpt = torch.load("lag-llama/lag-llama.ckpt", map_location=torch.device('cpu'))
    estimator_args = ckpt["hyper_parameters"]["model_kwargs"]

    estimator = LagLlamaEstimator(
        ckpt_path="lag-llama/lag-llama.ckpt",
        prediction_length=prediction_length,
        context_length=context_length,

        # estimator args
        input_size=estimator_args["input_size"],
        n_layer=estimator_args["n_layer"],
        n_embd_per_head=estimator_args["n_embd_per_head"],
        n_head=estimator_args["n_head"],
        scaling=estimator_args["scaling"],
        time_feat=estimator_args["time_feat"],

        nonnegative_pred_samples=nonnegative_pred_samples,

        # linear positional encoding scaling
        rope_scaling={
            "type": "linear",
            "factor": max(1.0, (context_length + prediction_length) / estimator_args["context_length"]),
        },

        batch_size=batch_size,
        num_parallel_samples=num_samples,
    )

    lightning_module = estimator.create_lightning_module()
    transformation = estimator.create_transformation()
    predictor = estimator.create_predictor(transformation, lightning_module)

    forecast_it, ts_it = make_evaluation_predictions(
        dataset=dataset,
        predictor=predictor,
        num_samples=num_samples
    )
    forecasts = list(tqdm(forecast_it, total=len(dataset), desc="Forecasting batches"))
    tss = list(tqdm(ts_it, total=len(dataset), desc="Ground truth"))

    return forecasts, tss


def forcast(datasets):
   
    device = "cuda"  # Use GPU if available
    #device = "CPU"  # Use GPU if available
    #TSS is the time series. 
    forecasts, tss = get_lag_llama_predictions(
        datasets.test,
        prediction_length=datasets.metadata.prediction_length,
        num_samples=num_samples,
        context_length=context_length,
        device=device
    )
    print('Finished forecast prediction')
    return forecasts, tss

def plot_forcast():
    plt.figure(figsize=(20, 15))
    date_formater = mdates.DateFormatter('%H:%M')  # Format to display hours and minutes
    plt.rcParams.update({'font.size': 15})

    # Iterate through the first 9 series, and plot the predicted samples
    for idx, (forecast, ts) in islice(enumerate(zip(forecasts, tss)), 9):
        ax = plt.subplot(3, 3, idx+1)

        # Plot the ground truth
        ground_truth = ts[-4 * prediction_length:].to_timestamp()
        plt.plot(ground_truth, label="target")

        # Plot the forecast
        forecast.plot(color='g')

        # Format x-axis
        plt.xticks(rotation=60)
        ax.xaxis.set_major_formatter(date_formater)
        ax.set_title(forecast.item_id)

        # Autoscale based on the ground truth
        ax.relim()  # Recompute the limits based on the data
        ax.autoscale_view()  # Autoscale the view to the new limits

    plt.gcf().tight_layout()
    plt.legend()
    plt.show()



def split_train_validation(datasets, validation_ratio=0.2):
    # Calculate the number of validation samples
    num_validation_samples = int(len(datasets.train) * validation_ratio)
    
    # Initialize the ValidationSplitSampler
    validation_sampler = ValidationSplitSampler(min_future=prediction_length)
    
    train_data = []
    val_data = []
    validation_count = 0
    
    for entry in datasets.train:
        # Extract the time series data from the entry
        ts = entry['target']
        
        # Use the validation sampler to determine if the entry should be in the validation set
        if validation_count < num_validation_samples and validation_sampler(ts):
            val_data.append(entry)
            validation_count += 1
        else:
            train_data.append(entry)
    
    return TrainDatasets(metadata=datasets.metadata, train=train_data, test=datasets.test), val_data

def finetune(datasets,val_data,max_epochs):
    print('Starting fine tuning')
    device="cuda"
    ckpt = torch.load("lag-llama/lag-llama.ckpt", map_location=device)
    estimator_args = ckpt["hyper_parameters"]["model_kwargs"]

    estimator = LagLlamaEstimator(
        ckpt_path="lag-llama/lag-llama.ckpt",
        prediction_length=prediction_length,
        context_length=context_length,
        #scaling="mean",
        nonnegative_pred_samples=True,
        batch_size=64,
        num_parallel_samples=num_parallel_samples,
        input_size=estimator_args["input_size"],
        n_layer=estimator_args["n_layer"],
        n_embd_per_head=estimator_args["n_embd_per_head"],
        n_head=estimator_args["n_head"],
        time_feat=estimator_args["time_feat"],
        trainer_kwargs={"max_epochs": max_epochs},
    )

    # Callbacks
    checkpoint_callback = ModelCheckpoint(
        monitor='val_loss',
        dirpath='checkpoints/',
        filename='best-checkpoint',
        save_top_k=1,
        mode='min'
    )

    early_stopping_callback = EarlyStopping(
        monitor='val_loss',
        patience=10,
        mode='min'
    )


    # Trainer
    trainer = Trainer(
        max_epochs=150,
        callbacks=[checkpoint_callback, early_stopping_callback],
        log_every_n_steps=1,
        val_check_interval=1  # Validate twice per epoch
    )

    # Training
    predictor = estimator.train(
        training_data=datasets.train,
        validation_data=val_data,
        cache_data=True,
        shuffle_buffer_length=7000,
        num_workers=4,
        batch_size=64,
        epochs=max_epochs,
        learning_rate=1e-4,
        early_stopping=True,
        checkpoint_callback=checkpoint_callback,
        use_single_instance_sampler=True,
        stratified_sampling="series",
        data_normalization="robust",
        n_layer=8,
        n_head=9,
        n_embd_per_head=16,
        time_feat=True,
        context_length=32,
        aug_prob=0.5,
        freq_mask_rate=0.5,
        freq_mixing_rate=0.25,
        weight_decay=0.0,
        dropout=0.0
    )
    print('Done fine tuning')
    return predictor

    # # Make evaluation predictions on the test dataset
    # forecast_it, ts_it = make_evaluation_predictions(
    #     dataset=datasets.test,
    #     predictor=predictor,
    #     num_samples=num_samples
    # )

    # print('Starting forecasting')

    # # Collect forecasts and ground truth time series
    # forecasts = list(tqdm(forecast_it, total=len(datasets.test), desc="Forecasting batches"))
    # print('Done forecasting')
    # tss = list(tqdm(ts_it, total=len(datasets.test), desc="Ground truth"))

    # # Evaluate the forecasts
    # evaluator = Evaluator()
    # agg_metrics, ts_metrics = evaluator(iter(tss), iter(forecasts))

    # # Print aggregated metrics
    # print(agg_metrics)
    # return forecasts, tss


def load_checkpoint_and_forecast(checkpoint_path, datasets, prediction_length, context_length, num_samples, device, batch_size=64, nonnegative_pred_samples=True, max_series=None):
    """
    Load a checkpoint and make forecasts using the fine-tuned model.

    Args:
        checkpoint_path (str): Path to the model checkpoint.
        datasets (TrainDatasets): The datasets containing train and test data.
        prediction_length (int): The length of the prediction horizon.
        context_length (int): The length of the context window.
        num_samples (int): The number of sample paths to generate.
        device (str): The device to use for computation (e.g., "cpu" or "cuda").
        batch_size (int, optional): The batch size for prediction. Defaults to 64.
        nonnegative_pred_samples (bool, optional): Whether to ensure nonnegative prediction samples. Defaults to True.
        max_series (int, optional): Maximum number of series to forecast. Defaults to None (forecast all series).

    Returns:
        tuple: A tuple containing the forecasts and the ground truth time series.
    """
    # Load the checkpoint
    ckpt = torch.load(checkpoint_path, map_location=device)
    estimator_args = ckpt["hyper_parameters"]["model_kwargs"]

    # Create the estimator with the loaded checkpoint
    estimator = LagLlamaEstimator(
        ckpt_path=checkpoint_path,
        prediction_length=prediction_length,
        context_length=context_length,

        # Estimator arguments
        input_size=estimator_args["input_size"],
        n_layer=estimator_args["n_layer"],
        n_embd_per_head=estimator_args["n_embd_per_head"],
        n_head=estimator_args["n_head"],
        scaling=estimator_args["scaling"],
        time_feat=estimator_args["time_feat"],

        nonnegative_pred_samples=nonnegative_pred_samples,

        # Linear positional encoding scaling
        rope_scaling={
            "type": "linear",
            "factor": max(1.0, (context_length + prediction_length) / estimator_args["context_length"]),
        },

        batch_size=batch_size,
        num_parallel_samples=num_parallel_samples,
    )

    # Create the predictor
    lightning_module = estimator.create_lightning_module()
    transformation = estimator.create_transformation()
    predictor = estimator.create_predictor(transformation, lightning_module)

    # Limit the number of series to forecast if max_series is specified
    if max_series is not None:
        dataset = list(datasets.test)[:max_series]
    else:
        dataset = datasets.test

    # Make evaluation predictions on the test dataset
    forecast_it, ts_it = make_evaluation_predictions(
        dataset=dataset,
        predictor=predictor,
        num_samples=num_samples
    )

    print('Starting forecasting')

    # Collect forecasts and ground truth time series
    forecasts = list(tqdm(forecast_it, total=len(dataset), desc="Forecasting batches"))
    print('Done forecasting')
    tss = list(tqdm(ts_it, total=len(dataset), desc="Ground truth"))

    # Evaluate the forecasts
    evaluator = Evaluator()
    agg_metrics, ts_metrics = evaluator(iter(tss), iter(forecasts))

    # Print aggregated metrics
    print(agg_metrics)
    return forecasts, tss 


def load_pickle(zip_file_path, extract_to_path='pickle/'):
    """
    Unzips a pickle file and loads its contents.

    Args:
        zip_file_path (str): Path to the zip file containing the pickle file.
        extract_to_path (str): Directory to extract the zip file contents to.

    Returns:
        datasets: The loaded datasets from the pickle file.
        file_size (int): Size of the loaded pickle file in bytes.
    """

    # Unzip the pickle file
    with zipfile.ZipFile(zip_file_path, 'r') as zipf:
        zipf.extractall(extract_to_path)
        # Get the name of the unzipped file
        unzipped_file_name = zipf.namelist()[0]
    print(f"Unzipped {zip_file_path} to {extract_to_path}")

    # Load the pickle file
    pickle_file_path = os.path.join(extract_to_path, unzipped_file_name)
    with open(pickle_file_path, 'rb') as f:
        datasets = pickle.load(f)
        file_size = os.path.getsize(pickle_file_path)
        print(f"Size of the loaded file: {file_size} bytes")

    # Verbose information about the dataset
    print("Verbose information about the dataset:")
    # print(f"Number of series in the training dataset: {len(datasets.train)}")
    # print(f"Number of series in the testing dataset: {len(datasets.test)}")


    return datasets, file_size


def save_and_push_to_github(commit_message="Auto-generated commit after tuning "):
            try:
                subprocess.run(["git", "pull"], check=True)
                # Add all changes to the staging area
                subprocess.run(["git", "add", "."], check=True)
                
                # Commit the changes
                subprocess.run(["git", "commit", "-m", commit_message], check=True)
                
                # Push the changes to the remote repository
                subprocess.run(["git", "push"], check=True)
                
                print("Changes have been successfully pushed to the GitHub repository.")
            except subprocess.CalledProcessError as e:
                print(f"An error occurred while trying to push to GitHub: {e}")









if __name__ == "__main__":
    #initialize()
    forecasts = None
    tss = None

    context_length = 950  # 600 minutes (10 hours)
    prediction_length = 120  #  starts at 8am, goes to 10am 
    num_parallel_samples = 10  # Number of sample paths to generate
    max_epochs = 500

    datasets, file_size = load_pickle('pickle/es-10yr-1min.zip', 'pickle/')
    #datasets, file_size = load_pickle('pickle/es-6month-1min.zip', 'pickle/')
    #datasets, file_size = load_pickle('pickle/fake_waves.zip', 'pickle/')
    datasets, val_data = split_train_validation(datasets, validation_ratio=0.3)

    
    mode = 'predict'
   
   
    if mode in ['train', 'all']:
        # Perform training operations
        print("Training mode selected.")
        finetune(datasets, val_data,max_epochs=max_epochs)  #the big call
   

    
    if mode in ['predict', 'all']:
        #######Steo 3:Forcast with fine tuned model 
    # Path to the fine-tuned checkpoint
        checkpoint_path = 'lightning_logs/version_37/checkpoints/epoch=388-step=19450.ckpt'
        max_series = 9  # Set the maximum number of series to forecast
        forecasts, tss = load_checkpoint_and_forecast(
            checkpoint_path=checkpoint_path,
            datasets=datasets,  # Pass the datasets object directly
            prediction_length=datasets.metadata.prediction_length,
            context_length=context_length,
            num_samples=num_parallel_samples,
            device="cuda",  # Use
            max_series=max_series  # Limit the number of series to forecast
        )


        #####Step 4: save the forecasts (time series) in their own picke for for further plotting in data_review.py 
        # Save the forecasts and tss to a pickle file in a folder called pickle
        checkpoint_dir = os.path.dirname(checkpoint_path)
        os.makedirs(checkpoint_dir, exist_ok=True)
        with open(os.path.join(checkpoint_dir, 'tuned_forecasts_tss.pkl'), 'wb') as f:
            pickle.dump({'forecasts': forecasts, 'tss': tss}, f)
            print(f"Forecasts and time series have been saved to '{os.path.join(checkpoint_dir, 'tuned_forecasts_tss.pkl')}'")

        

       

    if mode in ['commit', 'all']:
        checkpoint_name = os.path.basename(checkpoint_path)
        commit_message = f"Auto-generated commit with forecasts from checkpoint {checkpoint_name}"
        save_and_push_to_github(commit_message)
