"use client";

import { useEffect, useState, type FormEvent } from "react";

type Todo = {
  id: string;
  text: string;
  completed: boolean;
};

const STORAGE_KEY = "todo-app:todos";

function createId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function TodoApp() {
  const [todos, setTodos] = useState<Todo[]>([]);
  const [input, setInput] = useState("");
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved) {
        setTodos(JSON.parse(saved));
      }
    } catch {
      // 破損したデータは無視する
    } finally {
      setIsLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!isLoaded) return;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(todos));
  }, [todos, isLoaded]);

  const addTodo = (e: FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    setTodos((prev) => [...prev, { id: createId(), text, completed: false }]);
    setInput("");
  };

  const toggleTodo = (id: string) => {
    setTodos((prev) =>
      prev.map((todo) =>
        todo.id === id ? { ...todo, completed: !todo.completed } : todo
      )
    );
  };

  const deleteTodo = (id: string) => {
    setTodos((prev) => prev.filter((todo) => todo.id !== id));
  };

  const remainingCount = todos.filter((todo) => !todo.completed).length;

  return (
    <div className="w-full max-w-md rounded-3xl border border-white bg-white/70 p-6 shadow-xl shadow-indigo-100 backdrop-blur-md sm:p-8">
      <header className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-800">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-indigo-500 text-base text-white">
            ✓
          </span>
          ToDo リスト
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          {todos.length === 0
            ? "今日のタスクを追加しましょう"
            : `残り ${remainingCount} 件 / 全 ${todos.length} 件`}
        </p>
      </header>

      <form onSubmit={addTodo} className="mb-6 flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="新しいタスクを入力..."
          className="flex-1 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-slate-700 placeholder:text-slate-300 outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
        />
        <button
          type="submit"
          className="shrink-0 rounded-xl bg-indigo-500 px-4 py-2.5 font-medium text-white transition hover:bg-indigo-600 active:scale-95"
        >
          追加
        </button>
      </form>

      {todos.length === 0 ? (
        <div className="py-12 text-center text-slate-300">
          <p className="text-4xl">🌿</p>
          <p className="mt-2 text-sm">タスクはまだありません</p>
        </div>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {todos.map((todo) => (
            <li
              key={todo.id}
              className="group flex items-center gap-3 rounded-xl px-2 py-2.5 transition hover:bg-slate-50"
            >
              <button
                type="button"
                onClick={() => toggleTodo(todo.id)}
                aria-label={todo.completed ? "未完了に戻す" : "完了にする"}
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 transition ${
                  todo.completed
                    ? "border-indigo-500 bg-indigo-500 text-white"
                    : "border-slate-300 text-transparent hover:border-indigo-400"
                }`}
              >
                <svg
                  viewBox="0 0 12 10"
                  fill="none"
                  className="h-2.5 w-2.5"
                  aria-hidden="true"
                >
                  <path
                    d="M1 5L4.5 8.5L11 1"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>

              <span
                className={`flex-1 break-all text-sm transition ${
                  todo.completed
                    ? "text-slate-300 line-through"
                    : "text-slate-700"
                }`}
              >
                {todo.text}
              </span>

              <button
                type="button"
                onClick={() => deleteTodo(todo.id)}
                aria-label="削除"
                className="shrink-0 rounded-lg p-1.5 text-slate-300 opacity-0 transition hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
              >
                <svg
                  viewBox="0 0 20 20"
                  fill="none"
                  className="h-4 w-4"
                  aria-hidden="true"
                >
                  <path
                    d="M4 6h12M8.5 9v5M11.5 9v5M5.5 6l.7 9.2a1 1 0 001 .8h5.6a1 1 0 001-.8L14.5 6M7.5 6V4a1 1 0 011-1h3a1 1 0 011 1v2"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
