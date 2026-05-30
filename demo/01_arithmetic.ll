@.fmt.int = private constant [4 x i8] c"%d\0A\00"

declare i32 @printf(ptr, ...)

define i32 @add(i32 %a, i32 %b) {
entry:
  %a.addr = alloca i32
  %b.addr = alloca i32
  %result = alloca i32
  store i32 %a, ptr %a.addr
  store i32 %b, ptr %b.addr
  %0 = load i32, ptr %a.addr
  %1 = load i32, ptr %b.addr
  %2 = add i32 %0, %1
  store i32 %2, ptr %result
  %3 = load i32, ptr %result
  ret i32 %3
}

define i32 @main() {
entry:
  %x = alloca i32
  %0 = call i32 @add(i32 20, i32 22)
  store i32 %0, ptr %x
  %1 = load i32, ptr %x
  call i32 (ptr, ...) @printf(ptr @.fmt.int, i32 %1)
  ret i32 0
}