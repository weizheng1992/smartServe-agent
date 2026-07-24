'use client';

import { ArrowRight, Loader2, Sparkles, XCircle } from 'lucide-react';
import type React from 'react';
import { Button } from './ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from './ui/card';
import { Input } from './ui/input';

interface LoginCardProps {
  email: string;
  setEmail: (val: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  isLoading: boolean;
  error: string;
}

export function LoginCard({ email, setEmail, onSubmit, isLoading, error }: LoginCardProps) {
  return (
    <div className="flex h-screen w-screen items-center justify-center bg-slate-950 text-slate-100 font-sans p-4">
      <Card className="w-full max-w-md bg-slate-900 border-slate-800 shadow-2xl relative overflow-hidden">
        <div className="absolute top-0 left-0 right-0 h-1.5 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500" />
        <CardHeader className="pt-8 pb-4 text-center">
          <div className="mx-auto mb-4 p-3 bg-indigo-600/10 border border-indigo-500/20 rounded-2xl w-fit animate-pulse">
            <Sparkles className="h-8 w-8 text-indigo-400" />
          </div>
          <CardTitle className="text-2xl font-bold bg-gradient-to-r from-white via-slate-100 to-slate-400 bg-clip-text text-transparent">
            分布式智能客服控制中心
          </CardTitle>
          <CardDescription className="text-slate-400 text-xs mt-1 font-sans">
            基于 Drizzle-PostgreSQL / LangGraph 的高并发工作流中台
          </CardDescription>
        </CardHeader>
        <CardContent className="px-6 py-4">
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-400 font-mono">
                演示用户邮箱登录
              </label>
              <Input
                type="email"
                placeholder="name@example.com (例如: demo@test.com)"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="bg-slate-950 border-slate-800 text-slate-100 placeholder-slate-600 focus-visible:ring-indigo-500 h-11 font-sans"
                required
              />
            </div>
            {error && (
              <div className="text-xs font-mono text-rose-400 bg-rose-500/10 border border-rose-500/20 px-3 py-2 rounded-lg flex items-center gap-2">
                <XCircle className="h-3.5 w-3.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}
            <Button
              type="submit"
              className="w-full bg-indigo-600 hover:bg-indigo-500 text-white h-11 font-semibold rounded-xl tracking-wide transition flex items-center justify-center gap-2"
              disabled={isLoading}
            >
              {isLoading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <>
                  <span>进入实时控制台</span>
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </Button>
          </form>
        </CardContent>
        <CardFooter className="pb-8 pt-2 px-6 border-t border-slate-800/60 flex justify-center text-center">
          <div className="text-[11px] text-slate-500 font-mono">
            ⚡ 系统处于高保真沙箱环境 • 自动创建物理隔离账户与会话
          </div>
        </CardFooter>
      </Card>
    </div>
  );
}
