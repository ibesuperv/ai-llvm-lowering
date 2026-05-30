; ModuleID = 'MiniLang'
source_filename = "MiniLang"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Define the format string for printf
@.fmt.int = private unnamed_addr constant [4 x i8] c"%d\0A\00", section "rodata", align 1

; Declare the printf function
declare i32 @printf(ptr, ...) #0

; Define the fibonacci function
define i32 @fibonacci(i32 %0) {
entry:
  %1 = icmp sle i32 %0, 0
  br i1 %1, label %if.then, label %if.else

if.then:
  ret i32 0

if.else:
  %2 = icmp eq i32 %0, 1
  br i1 %2, label %if.end, label %fib.end

if.end:
  ret i32 1

fib.end:
  %3 = sub i32 %0, 1
  %4 = call i32 @fibonacci(i32 %3)
  %5 = sub i32 %0, 2
  %6 = call i32 @fibonacci(i32 %5)
  %7 = add i32 %4, %6
  ret i32 %7
}

; Define the main function
define i32 @main() {
entry:
  %0 = call i32 @fibonacci(i32 10)
  %1 = call i32 @printf(ptr @.fmt.int, i32 %0)
  ret i32 0
}

attributes #0 = { nofree nosync nounwind willreturn }