## Task
Envision yourself working at OTTO, engaging with the business analyst of your team regarding the recent meeting with the
marketing department. You inquire about the next steps for the data pipeline supporting the PowerBI reports.
The business analyst reveals that the marketing department is keen on a new visualization depicting the financial data
for January 2025, where they can see the revenue of every product for every day (even if it was not sold).

Further discussion with the analyst covers the required data model for the PowerBI reports.
He notes that the current data model is straightforward, comprising a single table named "revenue" with the following
columns (excluding technical column(s)):

- sku_id (TEXT)
- date_id (DATE)
- price (REAL)
- sales (INT)
- revenue (REAL)

With this in mind, you plan to establish a new data pipeline to **generate the new table within the existing database**.
You will utilize data from the existing "product" and "sales" data (csv and or db) to construct the new table.

## Technical Requirements & Data
Our operations are conducted within GCP, utilizing BigQuery as our data warehouse. However, for this interview task,
we will opt for a local database (sqlite) with two tables already provided:
- product: all the product data is in there.
- sales: only products that have been sold are in there. order_id is the identifier of the basket and every product
(sku) can be sold multiple times in different orders every day.

## Expectations
Approach the task with a production mindset and act like you are preparing a pull request for discussion.
Please write two solutions for the task, with a highlight on each of the following languages:
- one in SQL
- one in Python

We expect a Makefile including at least two targets:
- env: to set up the venv environment
- run: to run both solutions

## Evaluation
You will have 10 minutes to present your approach, followed by a discussion lasting up to 20 minutes.
You do not need to prepare slides, we just want to discuss your code directly as in a pull request. You can use
your preferred IDE or text editor to present your code.

## Submission
Please submit your solution via email to your OTTO contact person. Ensure your submission is received by 9 a.m. CEST
two working days before the interview at the latest.
