import pickle
global forecasts, tss

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from itertools import islice
import pandas as pd


def load_forecasts(file_path):
    with open(file_path, 'rb') as f:
        data = pickle.load(f)
    forecasts = data['forecasts']
    tss = data['tss']
    return forecasts, tss



def debug_forecasts_tss(forecasts, tss):
    print(f"Number of series in forecasts: {len(forecasts)}")
    print(f"Number of series in tss: {len(tss)}")
    
    for i, (forecast, ts) in enumerate(zip(forecasts, tss)):
        print(f"\nSeries {i}:")
        print(f"  Forecast length: {len(forecast.mean)}")
        print(f"  Time series length: {len(ts)}")

def plot_time_series(forecasts, tss, context_length, prediction_length):
    plt.figure(figsize=(20, 15))
    date_formatter = mdates.DateFormatter('%H:%M')  # Format to display hours and minutes
    plt.rcParams.update({'font.size': 15})

    # Iterate through the first 9 series, and plot the predicted samples
    for idx, (forecast, ts) in islice(enumerate(zip(forecasts, tss)), 9):
        ax = plt.subplot(3, 3, idx+1)

        # Convert PeriodIndex to Timestamp
        ts = ts.to_timestamp()

        # Print debug information about the series
        print(f"\nSeries {idx}:")
        print(f"  Total length of time series: {len(ts)}")
        print(f"  Forecast length: {len(forecast.mean)}")

        # Adjust context and prediction lengths if the series is too short
        total_length = len(ts)
        if total_length < context_length + prediction_length:
            print(f"Adjusting lengths for series {idx} because it is too short.")
            context_length = total_length // 2
            prediction_length = total_length - context_length

        # Calculate indices for context and prediction
        context_end_idx = ts.index[-prediction_length - 1]
        context_start_idx = context_end_idx - pd.Timedelta(minutes=context_length - 1)
        ground_truth_start_idx = context_end_idx + pd.Timedelta(minutes=1)
        ground_truth_end_idx = ground_truth_start_idx + pd.Timedelta(minutes=prediction_length - 1)

        # Print debug information about the indices
        print(f"  Context start index: {context_start_idx}")
        print(f"  Context end index: {context_end_idx}")
        print(f"  Ground truth start index: {ground_truth_start_idx}")
        print(f"  Ground truth end index: {ground_truth_end_idx}")

        # Extract context and ground truth series
        context_series = ts[context_start_idx:context_end_idx]
        ground_truth_series = ts[ground_truth_start_idx:ground_truth_end_idx]

        # Print debug information about the extracted series
        print(f"  Context series length: {len(context_series)}")
        print(f"  Ground truth series length: {len(ground_truth_series)}")

        # Plot the context window
        plt.plot(context_series.index, context_series, color='blue', label="context")

        # Plot the ground truth
        plt.plot(ground_truth_series.index, ground_truth_series, color='red', label="ground truth")

        # Plot the forecast
        forecast_start_idx = ground_truth_start_idx
        forecast_end_idx = forecast_start_idx + pd.Timedelta(minutes=len(forecast.mean) - 1)
        forecast_index = pd.date_range(start=forecast_start_idx, end=forecast_end_idx, freq='T')
        forecast_series = pd.Series(forecast.mean, index=forecast_index)
        plt.plot(forecast_series.index, forecast_series, color='green', label="forecast")

        # Combine context and ground truth to set y-axis limits
        combined_series = pd.concat([context_series, ground_truth_series])
        y_min, y_max = combined_series.min().min(), combined_series.max().max()
        y_range = y_max - y_min
        y_padding = y_range * 0.1
        ax.set_ylim(y_min - y_padding, y_max + y_padding)

        # Set x-axis limits to match the exact range of the context and forecast periods
        ax.set_xlim(context_start_idx, forecast_end_idx)

        # Format x-axis
        plt.xticks(rotation=60)
        ax.xaxis.set_major_formatter(date_formatter)
        ax.set_title(forecast.item_id)

        # Add legend
        ax.legend()

    plt.gcf().tight_layout()
    plt.show()


if __name__ == "__main__":
    
    # #zero shot predictions
    # forecasts, tss = load_forecasts('pickle/forecasts_tss.pkl')
    # plot_time_series(forecasts, tss, context_length=960, prediction_length=360)
    # print('done')

      
    # #fine tuned predictions
    forecasts, tss = load_forecasts('pickle/tuned_forecasts_tss.pkl')
    plot_time_series(forecasts, tss, context_length=960, prediction_length=360)
    print('done')