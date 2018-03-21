#pragma once

#include "utils/Errors.h"
#include <cuda_runtime.h>

/** Allocate GPU memory, giving size in unit of sizeof(T) */
template <class T>
inline void gpu_malloc(T *&ptr, size_t size)
{
  checkCudaErrors(cudaMalloc((void **)&ptr, sizeof(T) * size));
}

template <class T>
inline void gpu_free(T *ptr)
{
  if (ptr)
  {
    cudaFree(ptr);
  }
}

/** Transfers data from host to device.
 *
 * If any pointer is null, it silently doesn't transfer.
 *
 * @param device Pointer to device-allocated memory
 * @param host Pointer to host-memory
 * @param size Number of elmentary T items to transfer
 */
template <class T>
inline void gpu_memcpy_h2d(T *device, const T *host, size_t size)
{
  if (!host || !device)
    return;
  checkCudaErrors(
      cudaMemcpy(device, host, sizeof(T) * size, cudaMemcpyHostToDevice));
}

/** Transfers data from device to host.
 *
 * If any pointer is null, it silently doesn't transfer.
 *
 * @param device Pointer to device-allocated memory
 * @param host Pointer to host-memory
 * @param size Number of elmentary T items to transfer
 */
template <class T>
inline void gpu_memcpy_d2h(T *host, const T *device, size_t size)
{
  if (!host || !device)
    return;
  checkCudaErrors(
      cudaMemcpy(host, device, sizeof(T) * size, cudaMemcpyDeviceToHost));
}

/** Wraps a device pointer in RAII fashion, allowing to set an externally
 * allocated pointer as well.
 *
 * If an externally-allocated pointer is set, it will return this one instead
 * and avoid internal allocation.
 */
template <class T>
class DevicePtrWrapper
{
public:
  /** Default constructor */
  DevicePtrWrapper() = default;
  /** Not copyable */
  DevicePtrWrapper(const DevicePtrWrapper &) = delete;
  /** Not copyable */
  DevicePtrWrapper &operator=(const DevicePtrWrapper &) = delete;
  /** Movable */
  DevicePtrWrapper(DevicePtrWrapper &&) = default;
  /** Movable */
  DevicePtrWrapper &operator=(DevicePtrWrapper &&) = default;

  /** Assign an external pointer to use.
   *
   * If null, the internal pointer will be used instead
   */
  DevicePtrWrapper &operator=(T *dptr)
  {
    set_external(dptr);
    return *this;
  }

  /** Allocates memory for the internal pointer.
   *
   * If an external pointer was set before, this function does not allocate
   * anything.
   *
   * If the internal pointer was already allocated and size <= previous size,
   * it doesn't allocate again.
   *
   * @param size Number of items to allocate memory for.
   */
  void allocate(size_t size)
  {
    if (!isExternal())
    {
      if (d_internal_ && size_ < size)
      {
        gpu_free(d_internal_);
      }
      if (d_internal_ && size_ >= size)
      {
        return;
      }

      gpu_malloc(d_internal_, size);
      size_ = size;
    }
  }

  /** Sets the external device pointer.
   *
   * Same as operator=
   */
  void set_external(T *d) { d_external_ = d; }

  /** Unsets the external pointer - interal will be used from then on.
   *
   * Effectively sets the external pointer to null.
   */
  void unset_external() { d_external_ = nullptr; }

  /** Check if external pointer is set */
  bool isExternal() const { return d_external_ != nullptr; }

  /** Amount of memory allocated for internal pointer. */
  size_t size() const { return size_; }

  /** Implicit conversion to bool - see if a pointer is set */
  operator bool() const { return get() != nullptr; }

  /** Get the underlying point (internal or external) */
  T *get() const
  {
    if (isExternal())
    {
      return d_external_;
    }
    else
    {
      return d_internal_;
    }
  }

  /** Destructor - deallocate memory for internal pointer. */
  ~DevicePtrWrapper()
  {
    if (d_internal_)
    {
      gpu_free(d_internal_);
    }
  }

private:
  T *d_external_ = nullptr;
  T *d_internal_ = nullptr;
  size_t size_ = 0;
};