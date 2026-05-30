; ModuleID = 'MiniLang'
source_filename = "MiniLang"
target datalayout = "e-m:e-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

; External declaration for printf
declare i32 @printf(ptr, ...) #0

; Format string for printf
@.fmt.int = private constant [4 x i8] c"%d\0A\00", section "rodata", align 1

; Function definition for factorial
define i32 @factorial(i32 %0) #0 {
entry:
  %1 = alloca i32, align 4
  store i32 %0, ptr %1, align 4
  %2 = load i32, ptr %1, align 4
  %3 = icmp sle i32 %2, 1
  br i1 %3, label %if.then, label %if.else

if.then:
  %4 = alloca i32, align 4
  store i32 1, ptr %4, align 4
  %5 = load i32, ptr %4, align 4
  ret i32 %5

if.else:
  %6 = load i32, ptr %1, align 4
  %7 = sub i32 %6, 1
  %8 = call i32 @factorial(i32 %7)
  %9 = mul i32 %6, %8
  ret i32 %9
}

; Function definition for main
define i32 @main() #0 {
entry:
  %0 = alloca i32, align 4
  %1 = call i32 @factorial(i32 5)
  store i32 %1, ptr %0, align 4
  %2 = load i32, ptr %0, align 4
  %3 = getelementptr inbounds [4 x i8], ptr @.fmt.int, i64 0, i64 0
  %4 = call i32 (ptr, ...) @printf(ptr %3, i32 %2)
  ret i32 0
}

attributes #0 = { noinline nounwind optnone uwtable "correctly-rounded-divide-sqrt-fp-math"="false" "disable-tail-calls"="false" "frame-pointer"="all" "less-precise-fpmad"="false" "min-legal-vector-width"="0" "no-infs-fp-math"="false" "no-jump-tables"="false" "no-nans-fp-math"="false" "no-signed-zeros-fp-math"="false" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "unsafe-fp-math"="false" "use-soft-float"="false" }