# ホストで動く単体テスト (実機不要):  make -C firmware/tests
CC ?= gcc
test: host_test test_stepper
	./host_test
	./test_stepper
test_stepper: test_stepper.c ../lib/mpb_stepper.c ../lib/mpb_stepper.h stub/mpb.h
	$(CC) -O1 -Wall -Wno-unused-function -Istub -I../lib -o $@ test_stepper.c
host_test: host_test.c ../lib/mpb_log.c ../lib/mpb_env.c ../lib/mpb_cie.h stub/mpb.h
	$(CC) -O1 -Wall -Wno-unused-function -Istub -I../lib -o $@ host_test.c
clean:
	rm -f host_test test_stepper
.PHONY: test clean
