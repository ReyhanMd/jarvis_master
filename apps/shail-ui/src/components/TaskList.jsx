import { useState, useEffect, useRef } from 'react';
import { getAllTasks } from '../services/api';
import TaskCard from './TaskCard';

export default function TaskList({ onTaskAwaitingApproval, onTaskUpdate }) {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const callbackRef = useRef(onTaskAwaitingApproval);
  const updateCallbackRef = useRef(onTaskUpdate);
  const previousTasksRef = useRef(new Map());

  // Keep callback refs updated
  useEffect(() => {
    callbackRef.current = onTaskAwaitingApproval;
  }, [onTaskAwaitingApproval]);

  useEffect(() => {
    updateCallbackRef.current = onTaskUpdate;
  }, [onTaskUpdate]);

  const fetchTasks = async () => {
    try {
      const data = await getAllTasks();
      setTasks(data);
      setError(null);

      // Check for tasks awaiting approval
      const awaitingApproval = data.find(t => t.status === 'awaiting_approval');
      if (awaitingApproval && callbackRef.current) {
        callbackRef.current(awaitingApproval);
      }

      // Notify about task updates for chat messages
      if (updateCallbackRef.current) {
        const currentTasksMap = new Map();
        data.forEach(task => {
          if (task.task_id) {
            currentTasksMap.set(task.task_id, task);
            
            // Check if task status changed or is new
            const previousTask = previousTasksRef.current.get(task.task_id);
            if (!previousTask || previousTask.status !== task.status) {
              // Task is new or status changed - notify chat
              updateCallbackRef.current(task);
            }
          }
        });
        previousTasksRef.current = currentTasksMap;
      }
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to fetch tasks');
      console.error('Fetch tasks error:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTasks();
    // Poll every 2 seconds
    const interval = setInterval(fetchTasks, 2000);
    return () => clearInterval(interval);
  }, []);

  if (loading && tasks.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-400">Loading tasks...</div>
      </div>
    );
  }

  if (error && tasks.length === 0) {
    return (
      <div className="p-4 bg-red-500/20 border border-red-500/50 rounded text-red-200">
        Error: {error}
      </div>
    );
  }

  if (tasks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-400">
        <p className="text-lg mb-2">No tasks yet</p>
        <p className="text-sm">Submit a task to get started</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {tasks.map((task) => (
        <TaskCard key={task.task_id} task={task} />
      ))}
    </div>
  );
}

