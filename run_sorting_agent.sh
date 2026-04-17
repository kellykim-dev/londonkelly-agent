#!/bin/bash

LOG=~/Desktop/sorting_agent.log
echo "========================================" >> $LOG
echo "Run started: $(date)" >> $LOG

cd ~/Desktop

echo "Sorting collections..." >> $LOG
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 sort_collections.py >> $LOG 2>&1

if [ $? -eq 0 ]; then
    echo "✅ Sort completed" >> $LOG
else
    echo "❌ Sort FAILED" >> $LOG
fi

echo "Updating hot items..." >> $LOG
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 update_hot_items.py >> $LOG 2>&1

if [ $? -eq 0 ]; then
    echo "✅ Hot items updated" >> $LOG
else
    echo "❌ Hot items FAILED" >> $LOG
fi

echo "Run finished: $(date)" >> $LOG
